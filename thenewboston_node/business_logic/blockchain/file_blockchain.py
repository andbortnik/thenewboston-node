import logging
import os.path
import re
from collections import namedtuple
from typing import Generator, Optional

import filelock
import msgpack
from cachetools import LRUCache
from more_itertools import always_reversible, ilen

from thenewboston_node.business_logic.exceptions import BlockchainLockedError, BlockchainUnlockedError
from thenewboston_node.business_logic.models.block import Block
from thenewboston_node.business_logic.models.blockchain_state import BlockchainState
from thenewboston_node.business_logic.storages.file_system import COMPRESSION_FUNCTIONS
from thenewboston_node.business_logic.storages.path_optimized_file_system import PathOptimizedFileSystemStorage
from thenewboston_node.core.logging import timeit
from thenewboston_node.core.utils.file_lock import ensure_locked, lock_method

from .base import BlockchainBase

logger = logging.getLogger(__name__)

# TODO(dmu) LOW: Move these constants to configuration files
ORDER_OF_BLOCKCHAIN_STATE_FILE = 10
ORDER_OF_BLOCK = 20

LAST_BLOCK_NUMBER_NONE_SENTINEL = '!'
# We need to zfill to maintain the nested structure of directories
BLOCKCHAIN_GENESIS_STATE_PREFIX = LAST_BLOCK_NUMBER_NONE_SENTINEL.zfill(ORDER_OF_BLOCKCHAIN_STATE_FILE)

BLOCKCHAIN_STATE_FILENAME_TEMPLATE = '{last_block_number}-arf.msgpack'
BLOCKCHAIN_STATE_FILENAME_RE = re.compile(
    BLOCKCHAIN_STATE_FILENAME_TEMPLATE.
    format(last_block_number=r'(?P<last_block_number>\d{,' + str(ORDER_OF_BLOCKCHAIN_STATE_FILE - 1) + r'}(?:!|\d))') +
    r'(?:|\.(?P<compression>{}))$'.format('|'.join(COMPRESSION_FUNCTIONS.keys()))
)

BLOCK_CHUNK_FILENAME_TEMPLATE = '{start}-{end}-block-chunk.msgpack'
BLOCK_CHUNK_FILENAME_RE = re.compile(
    BLOCK_CHUNK_FILENAME_TEMPLATE.format(start=r'(?P<start>\d+)', end=r'(?P<end>\d+)') +
    r'(?:|\.(?P<compression>{}))$'.format('|'.join(COMPRESSION_FUNCTIONS.keys()))
)

DEFAULT_BLOCKCHAIN_STATES_SUBDIR = 'blockchain-states'
DEFAULT_BLOCKS_SUBDIR = 'blocks'

DEFAULT_BLOCK_CHUNK_SIZE = 100

LOCKED_EXCEPTION = BlockchainLockedError('Blockchain locked. Probably it is being modified by another process')
EXPECTED_LOCK_EXCEPTION = BlockchainUnlockedError('Blockchain was expected to be locked')

BlockChunkFilenameMeta = namedtuple('BlockChunkFilenameMeta', 'start end compression')
BlockchainFilenameMeta = namedtuple('BlockchainFilenameMeta', 'last_block_number compression')


def make_blockchain_state_filename(last_block_number=None):
    # We need to zfill LAST_BLOCK_NUMBER_NONE_SENTINEL to maintain the nested structure of directories
    prefix = (LAST_BLOCK_NUMBER_NONE_SENTINEL
              if last_block_number is None else str(last_block_number)).zfill(ORDER_OF_BLOCKCHAIN_STATE_FILE)
    return BLOCKCHAIN_STATE_FILENAME_TEMPLATE.format(last_block_number=prefix)


def get_blockchain_state_filename_meta(filename):
    match = BLOCKCHAIN_STATE_FILENAME_RE.match(filename)
    if match:
        last_block_number_str = match.group('last_block_number')

        if last_block_number_str.endswith(LAST_BLOCK_NUMBER_NONE_SENTINEL):
            last_block_number = None
        else:
            last_block_number = int(last_block_number_str)

        return BlockchainFilenameMeta(last_block_number, match.group('compression') or None)

    return None


def get_blockchain_state_file_path_meta(file_path):
    return get_blockchain_state_filename_meta(os.path.basename(file_path))


def make_block_chunk_filename(start: int, end: int):
    start_block_str = str(start).zfill(ORDER_OF_BLOCK)
    end_block_str = str(end).zfill(ORDER_OF_BLOCK)

    return BLOCK_CHUNK_FILENAME_TEMPLATE.format(start=start_block_str, end=end_block_str)


def get_block_chunk_filename_meta(file_path):
    filename = os.path.basename(file_path)
    match = BLOCK_CHUNK_FILENAME_RE.match(filename)
    if match:
        start = int(match.group('start'))
        end = int(match.group('end'))
        assert start <= end
        return BlockChunkFilenameMeta(start, end, match.group('compression') or None)

    return None


def get_block_chunk_file_path_meta(file_path):
    return get_block_chunk_filename_meta(os.path.basename(file_path))


class FileBlockchain(BlockchainBase):

    def __init__(
        self,
        *,
        base_directory,

        # Account root files
        account_root_files_subdir=DEFAULT_BLOCKCHAIN_STATES_SUBDIR,
        account_root_files_cache_size=128,
        account_root_files_storage_kwargs=None,

        # Blocks
        blocks_subdir=DEFAULT_BLOCKS_SUBDIR,
        block_chunk_size=DEFAULT_BLOCK_CHUNK_SIZE,
        blocks_cache_size=None,
        blocks_storage_kwargs=None,
        lock_filename='file.lock',
        **kwargs
    ):
        if not os.path.isabs(base_directory):
            raise ValueError('base_directory must be an absolute path')

        kwargs.setdefault('snapshot_period_in_blocks', block_chunk_size)
        super().__init__(**kwargs)

        self.block_chunk_size = block_chunk_size

        account_root_files_directory = os.path.join(base_directory, account_root_files_subdir)
        block_directory = os.path.join(base_directory, blocks_subdir)
        self.base_directory = base_directory

        self.block_storage = PathOptimizedFileSystemStorage(base_path=block_directory, **(blocks_storage_kwargs or {}))
        self.blockchain_states_storage = PathOptimizedFileSystemStorage(
            base_path=account_root_files_directory, **(account_root_files_storage_kwargs or {})
        )

        self.account_root_files_cache_size = account_root_files_cache_size
        self.blocks_cache_size = blocks_cache_size

        self.blockchain_states_cache: Optional[LRUCache] = None
        self.blocks_cache: Optional[LRUCache] = None
        self.initialize_caches()

        self._file_lock = None
        self.lock_filename = lock_filename

    @property
    def file_lock(self):
        file_lock = self._file_lock
        if file_lock is None:
            base_directory = self.base_directory
            os.makedirs(base_directory, exist_ok=True)
            lock_file_path = os.path.join(base_directory, self.lock_filename)
            self._file_lock = file_lock = filelock.FileLock(lock_file_path, timeout=0)

        return file_lock

    @lock_method(lock_attr='file_lock', exception=LOCKED_EXCEPTION)
    def clear(self):
        self.initialize_caches()
        self.block_storage.clear()
        self.blockchain_states_storage.clear()

    def initialize_caches(self):
        self.blockchain_states_cache = LRUCache(self.account_root_files_cache_size)
        self.blocks_cache = LRUCache(
            # We do not really need to cache more than `snapshot_period_in_blocks` blocks since
            # we use use account root file as a base
            self.snapshot_period_in_blocks * 2 if self.blocks_cache_size is None else self.blocks_cache_size
        )

    # Account root files methods
    @lock_method(lock_attr='file_lock', exception=LOCKED_EXCEPTION)
    def add_blockchain_state(self, blockchain_state: BlockchainState):
        return super().add_blockchain_state(blockchain_state)

    @ensure_locked(lock_attr='file_lock', exception=EXPECTED_LOCK_EXCEPTION)
    def persist_blockchain_state(self, blockchain_state: BlockchainState):
        storage = self.blockchain_states_storage
        last_block_number = blockchain_state.last_block_number

        filename = make_blockchain_state_filename(last_block_number)
        storage.save(filename, blockchain_state.to_messagepack(), is_final=True)

    def _load_blockchain_states(self, file_path):
        cache = self.blockchain_states_cache
        account_root_file = cache.get(file_path)
        if account_root_file is None:
            storage = self.blockchain_states_storage
            assert storage.is_finalized(file_path)
            account_root_file = BlockchainState.from_messagepack(storage.load(file_path))
            cache[file_path] = account_root_file

        return account_root_file

    def _yield_blockchain_states(self, direction) -> Generator[BlockchainState, None, None]:
        assert direction in (1, -1)

        storage = self.blockchain_states_storage
        for file_path in storage.list_directory(sort_direction=direction):
            yield self._load_blockchain_states(file_path)

    def yield_blockchain_states(self) -> Generator[BlockchainState, None, None]:
        yield from self._yield_blockchain_states(1)

    def yield_blockchain_states_reversed(self) -> Generator[BlockchainState, None, None]:
        yield from self._yield_blockchain_states(-1)

    def get_blockchain_states_count(self) -> int:
        storage = self.blockchain_states_storage
        return ilen(storage.list_directory())

    # Blocks methods
    @lock_method(lock_attr='file_lock', exception=LOCKED_EXCEPTION)
    def add_block(self, block: Block, validate=True):
        return super().add_block(block, validate)

    @ensure_locked(lock_attr='file_lock', exception=EXPECTED_LOCK_EXCEPTION)
    def persist_block(self, block: Block):
        storage = self.block_storage
        block_chunk_size = self.block_chunk_size

        block_number = block.message.block_number
        chunk_number, offset = divmod(block_number, block_chunk_size)

        chunk_block_number_start = chunk_number * block_chunk_size

        if chunk_block_number_start == block_number:
            append_end = block_number
        else:
            assert chunk_block_number_start < block_number
            append_end = block_number - 1

        append_filename = make_block_chunk_filename(start=chunk_block_number_start, end=append_end)
        filename = make_block_chunk_filename(start=chunk_block_number_start, end=block_number)

        storage.append(append_filename, block.to_messagepack())

        if append_filename != filename:
            storage.move(append_filename, filename)

        if offset == block_chunk_size - 1:
            storage.finalize(filename)

    def yield_blocks(self) -> Generator[Block, None, None]:
        yield from self._yield_blocks(1)

    @timeit(verbose_args=True, is_method=True)
    def yield_blocks_reversed(self) -> Generator[Block, None, None]:
        yield from self._yield_blocks(-1)

    def yield_blocks_from(self, block_number: int) -> Generator[Block, None, None]:
        for file_path in self._list_block_directory():
            meta = get_block_chunk_file_path_meta(file_path)
            if meta is None:
                logger.warning('File %s has invalid name format', file_path)
                continue

            if meta.end < block_number:
                continue

            yield from self._yield_blocks_from_file_cached(file_path, direction=1, start=max(meta.start, block_number))

    def get_block_by_number(self, block_number: int) -> Optional[Block]:
        assert self.blocks_cache
        block = self.blocks_cache.get(block_number)
        if block is not None:
            return block

        try:
            return next(self.yield_blocks_from(block_number))
        except StopIteration:
            return None

    def get_block_count(self) -> int:
        count = 0
        for file_path in self._list_block_directory():
            meta = get_block_chunk_file_path_meta(file_path)
            if meta is None:
                logger.warning('File %s has invalid name format', file_path)
                continue

            count += meta.end - meta.start + 1

        return count

    @timeit(verbose_args=True, is_method=True)
    def _yield_blocks(self, direction) -> Generator[Block, None, None]:
        assert direction in (1, -1)

        for file_path in self._list_block_directory(direction):
            yield from self._yield_blocks_from_file_cached(file_path, direction)

    def _yield_blocks_from_file_cached(self, file_path, direction, start=None):
        assert direction in (1, -1)

        meta = get_block_chunk_file_path_meta(file_path)
        if meta is None:
            logger.warning('File %s has invalid name format', file_path)
            return

        file_start = meta.start
        file_end = meta.end
        if direction == 1:
            next_block_number = cache_start = file_start if start is None else start
            cache_end = file_end
        else:
            cache_start = file_start
            next_block_number = cache_end = file_end if start is None else start

        for block in self._yield_blocks_from_cache(cache_start, cache_end, direction):
            assert next_block_number == block.message.block_number
            next_block_number += direction
            yield block

        if file_start <= next_block_number <= file_end:
            yield from self._yield_blocks_from_file(file_path, direction, start=next_block_number)

    def _yield_blocks_from_file(self, file_path, direction, start=None):
        assert direction in (1, -1)
        storage = self.block_storage

        unpacker = msgpack.Unpacker()
        unpacker.feed(storage.load(file_path))
        if direction == -1:
            unpacker = always_reversible(unpacker)

        for block_compact_dict in unpacker:
            block = Block.from_compact_dict(block_compact_dict)
            block_number = block.message.block_number
            # TODO(dmu) HIGH: Implement a better skip
            if start is not None:
                if direction == 1 and block_number < start:
                    continue
                elif direction == -1 and block_number > start:
                    continue

            self.blocks_cache[block_number] = block
            yield block

    def _yield_blocks_from_cache(self, start_block_number, end_block_number, direction):
        assert direction in (1, -1)

        iter_ = range(start_block_number, end_block_number + 1)
        if direction == -1:
            iter_ = always_reversible(iter_)

        for block_number in iter_:
            block = self.blocks_cache.get(block_number)
            if block is None:
                break

            yield block

    def _list_block_directory(self, direction=1):
        yield from self.block_storage.list_directory(sort_direction=direction)
