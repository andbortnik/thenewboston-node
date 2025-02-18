import bz2
import gzip
import logging
import lzma
import os
import shutil
import stat
from pathlib import Path
from typing import Union

from thenewboston_node.business_logic import exceptions
from thenewboston_node.core.logging import timeit_method
from thenewboston_node.core.utils.atomic_write import atomic_write_append

# TODO(dmu) LOW: Support more / better compression methods
COMPRESSION_FUNCTIONS = {
    'gz': lambda data: gzip.compress(data, compresslevel=9),
    'bz2': lambda data: bz2.compress(data, compresslevel=9),
    'xz': lzma.compress
}

DECOMPRESSION_FUNCTIONS = {
    'gz': gzip.decompress,
    'bz2': bz2.decompress,
    'xz': lzma.decompress,
}

STAT_WRITE_PERMS_ALL = stat.S_IWGRP | stat.S_IWUSR | stat.S_IWOTH

logger = logging.getLogger(__name__)


def ensure_directory_exists_for_file_path(file_path):
    directory = os.path.dirname(file_path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def drop_write_permissions(filename):
    current_mode = os.stat(filename).st_mode
    mode = current_mode - (current_mode & STAT_WRITE_PERMS_ALL)
    os.chmod(filename, mode)


def has_write_permissions(filename):
    return bool(os.stat(filename).st_mode & STAT_WRITE_PERMS_ALL)


def strip_compression_extension(filename):
    for compressor in DECOMPRESSION_FUNCTIONS:
        if filename.endswith('.' + compressor):
            return filename[:-len(compressor) - 1]

    return filename


def exist_compressed_file(file_path):
    for decompressor in DECOMPRESSION_FUNCTIONS:
        path = file_path + '.' + decompressor
        if os.path.exists(path):
            return True
    return False


class FileSystemStorage:
    """
    Compressing / decompressing storage for capacity optimization
    """

    def __init__(self, base_path: Union[str, Path], compressors=tuple(COMPRESSION_FUNCTIONS), temp_dir='.tmp'):
        self.base_path = Path(base_path).resolve()
        self.compressors = compressors
        self.temp_dir = self.base_path / temp_dir

    def clear(self):
        shutil.rmtree(self.base_path, ignore_errors=True)

    @timeit_method()
    def save(self, file_path: Union[str, Path], binary_data: bytes, is_final=False):
        self._persist(file_path, binary_data, 'wb', is_final=is_final)

    def load(self, file_path: Union[str, Path]) -> bytes:
        file_path = self._get_absolute_path(file_path)
        for decompressor, func in DECOMPRESSION_FUNCTIONS.items():
            path = str(file_path) + '.' + decompressor
            try:
                with open(path, mode='rb') as fo:
                    data = fo.read()
            except OSError:
                continue

            return func(data)  # type: ignore

        with open(file_path, mode='rb') as fo:
            return fo.read()

    def append(self, file_path: Union[str, Path], binary_data: bytes, is_final=False):
        self._persist(file_path, binary_data, 'ab', is_final=is_final)

    def finalize(self, file_path: Union[str, Path]):
        file_path = self._get_absolute_path(file_path)
        self._finalize(file_path)

    def list_directory(self, prefix=None, sort_direction=1):
        # TODO(dmu) HIGH: Implement it to list only current directory to be consitent with other methods
        #                     that are intended to operate on a give directory without nesting
        raise NotImplementedError

    def move(self, source: Union[str, Path], destination: Union[str, Path]):
        source = self._get_absolute_path(source)
        destination = self._get_absolute_path(destination)
        ensure_directory_exists_for_file_path(destination)
        os.rename(source, destination)

    def is_finalized(self, file_path: Union[str, Path]):
        file_path = self._get_absolute_path(file_path)
        return self._is_finalized(file_path)

    def _get_absolute_path(self, file_path: Union[str, Path]) -> Path:
        base_path = self.base_path
        path = Path(file_path)
        abs_path = (base_path / path).resolve()

        if path.is_absolute():
            raise ValueError(f"Cannot use absolute path: '{path}'")

        if not abs_path.is_relative_to(base_path):
            raise ValueError(f"Path '{abs_path}' is not relative to '{base_path}'")

        return abs_path

    @timeit_method()
    def _compress(self, file_path: Path) -> Path:
        compressors = self.compressors
        if not compressors:
            return file_path

        with open(file_path, 'rb') as fo:
            original_data = fo.read()

        logger.debug('File %s size: %s bytes', file_path, len(original_data))
        best_filename = file_path
        best_data = original_data

        for compressor in self.compressors:
            compress_function = COMPRESSION_FUNCTIONS[compressor]
            compressed_data = compress_function(original_data)  # type: ignore
            compressed_size = len(compressed_data)
            logger.debug(
                'File %s compressed with %s size: %s bytes (%.2f ratio)', file_path, compressor, compressed_size,
                compressed_size / len(original_data)
            )
            # TODO(dmu) LOW: For compressed_size == best[0] choose fastest compression
            if compressed_size < len(best_data):
                best_filename = Path(str(file_path) + '.' + compressor)
                best_data = compressed_data
                logger.debug('New best %s: %s size', best_filename, len(best_data))

        if best_filename != file_path:
            logger.debug('Writing compressed file: %s (%s bytes)', best_filename, len(best_data))
            self._write_file(best_filename, best_data, mode='wb')

            logger.debug('Removing %s', file_path)
            os.remove(file_path)

        return best_filename

    def _persist(self, file_path: Union[str, Path], binary_data: bytes, mode, is_final=False):
        file_path = self._get_absolute_path(file_path)
        ensure_directory_exists_for_file_path(str(file_path))

        # TODO(dmu) HIGH: Optimize for 'wb' mode so we do not need to reread the file from
        #                 filesystem to compress it
        self._write_file(file_path, binary_data, mode)

        if is_final:
            self._finalize(file_path)

    def _finalize(self, file_path: Path):
        new_filename = self._compress(file_path)
        drop_write_permissions(new_filename)

    @staticmethod
    def _is_finalized(file_path: Path):
        return (
            exist_compressed_file(str(file_path)) or
            (os.path.exists(file_path) and not has_write_permissions(file_path))
        )

    def _write_file(self, file_path: Path, binary_data: bytes, mode):
        if self._is_finalized(file_path):
            raise exceptions.FinalizedFileWriteError(f'Could not write to finalized file: {file_path}')

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        with atomic_write_append(file_path, mode=mode, dir=self.temp_dir) as fo:
            fo.write(binary_data)
