import pytest

from thenewboston_node.business_logic.models.block import Block


@pytest.fixture(autouse=True)
def set_up(file_blockchain_w_memory_storage, user_account, treasury_account_signing_key):
    signing_key = treasury_account_signing_key
    blockchain = file_blockchain_w_memory_storage
    filename = '0000-0003-block-chunk.msgpack'

    block0 = Block.from_main_transaction(blockchain, user_account, 10, signing_key=signing_key)
    blockchain.block_storage.append(filename, block0.to_messagepack())

    block1 = Block.from_main_transaction(blockchain, user_account, 20, signing_key=signing_key)
    blockchain.block_storage.append(filename, block1.to_messagepack())

    block2 = Block.from_main_transaction(blockchain, user_account, 50, signing_key=signing_key)
    blockchain.block_storage.append(filename, block2.to_messagepack())

    block3 = Block.from_main_transaction(blockchain, user_account, 70, signing_key=signing_key)
    blockchain.block_storage.append(filename, block3.to_messagepack())


def get_block_numbers(blocks):
    return list(map(lambda b: b.message.block_number, blocks))


def test_can_yield_blocks(file_blockchain_w_memory_storage):
    blocks = list(file_blockchain_w_memory_storage.yield_blocks())

    assert get_block_numbers(blocks) == [0, 1, 2, 3]


def test_can_yield_blocks_reversed(file_blockchain_w_memory_storage):
    blocks = list(file_blockchain_w_memory_storage.yield_blocks_reversed())

    assert get_block_numbers(blocks) == [3, 2, 1, 0]


def test_yield_blocks_from_file_cache(file_blockchain_w_memory_storage):
    filename = '0000-0003-block-chunk.msgpack'
    blocks = file_blockchain_w_memory_storage._yield_blocks_from_file_cached(filename, -1, start=1)

    assert get_block_numbers(blocks) == [1, 0]


@pytest.mark.parametrize(
    'block_number, expected_block_numbers', (
        (0, [0, 1, 2, 3]),
        (1, [1, 2, 3]),
        (2, [2, 3]),
        (3, [3]),
    )
)
def test_can_yield_blocks_from(file_blockchain_w_memory_storage, block_number, expected_block_numbers):
    blocks = file_blockchain_w_memory_storage.yield_blocks_from(block_number=block_number)

    assert get_block_numbers(blocks) == expected_block_numbers


def test_can_get_block_count(file_blockchain_w_memory_storage):
    assert file_blockchain_w_memory_storage.get_block_count() == 4


def test_can_get_block_by_number(file_blockchain_w_memory_storage):
    received_block = file_blockchain_w_memory_storage.get_block_by_number(block_number=1)

    assert received_block.message.block_number == 1


def test_get_block_by_number_returns_none_if_not_exist(file_blockchain_w_memory_storage):
    received_block = file_blockchain_w_memory_storage.get_block_by_number(block_number=999)

    assert received_block is None


def test_can_get_first_block(file_blockchain_w_memory_storage):
    block = file_blockchain_w_memory_storage.get_first_block()
    assert block.message.block_number == 0


def test_can_get_last_block(file_blockchain_w_memory_storage):
    block = file_blockchain_w_memory_storage.get_last_block()
    assert block.message.block_number == 3


def test_can_yield_blocks_till_snapshot(file_blockchain_w_memory_storage):
    blocks = list(file_blockchain_w_memory_storage.yield_blocks_till_snapshot())
    assert get_block_numbers(blocks) == [3, 2, 1, 0]


def test_can_yield_blocks_till_snapshot_from_block_number(file_blockchain_w_memory_storage):
    blocks = file_blockchain_w_memory_storage.yield_blocks_till_snapshot(from_block_number=1)

    assert get_block_numbers(blocks) == [1, 0]
