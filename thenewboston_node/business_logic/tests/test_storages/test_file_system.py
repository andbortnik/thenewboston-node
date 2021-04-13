import gzip
import os.path
import stat
from os import stat as os_stat

import pytest

from thenewboston_node.business_logic.storages import exceptions
from thenewboston_node.business_logic.storages.decorators import make_optimized_file_path
from thenewboston_node.business_logic.storages.file_system import FileSystemStorage, get_filesystem_storage
from thenewboston_node.business_logic.tests.test_storages.util import compress, decompress, mkdir_and_touch


def test_make_optimized_file_path():
    assert make_optimized_file_path('a', 0) == 'a'
    assert make_optimized_file_path('a', 1) == 'a/a'
    assert make_optimized_file_path('a', 2) == 'a/a'
    assert make_optimized_file_path('a', 3) == 'a/a'

    assert make_optimized_file_path('a.json', 0) == 'a.json'
    assert make_optimized_file_path('a.json', 1) == 'a/a.json'
    assert make_optimized_file_path('a.json', 2) == 'a/a.json'
    assert make_optimized_file_path('a.json', 3) == 'a/a.json'

    assert make_optimized_file_path('d/a.json', 0) == 'd/a.json'
    assert make_optimized_file_path('d/a.json', 1) == 'd/a/a.json'
    assert make_optimized_file_path('d/a.json', 2) == 'd/a/a.json'
    assert make_optimized_file_path('d/a.json', 3) == 'd/a/a.json'

    assert make_optimized_file_path('/d/a.json', 0) == '/d/a.json'
    assert make_optimized_file_path('/d/a.json', 1) == '/d/a/a.json'
    assert make_optimized_file_path('/d/a.json', 2) == '/d/a/a.json'
    assert make_optimized_file_path('/d/a.json', 3) == '/d/a/a.json'

    assert make_optimized_file_path('/d/abc.json', 0) == '/d/abc.json'
    assert make_optimized_file_path('/d/abc.json', 1) == '/d/a/abc.json'
    assert make_optimized_file_path('/d/abc.json', 2) == '/d/a/b/abc.json'
    assert make_optimized_file_path('/d/abc.json', 3) == '/d/a/b/c/abc.json'

    assert make_optimized_file_path('/d/abc-def-ghi.json', 8) == '/d/a/b/c/d/e/f/g/h/abc-def-ghi.json'
    assert make_optimized_file_path('/d/abc-def ghi.json', 8) == '/d/a/b/c/d/e/f/g/h/abc-def ghi.json'
    assert make_optimized_file_path('/d/ABCDEFGHI.json', 8) == '/d/a/b/c/d/e/f/g/h/ABCDEFGHI.json'
    assert make_optimized_file_path('/d/12345abcd.json', 8) == '/d/1/2/3/4/5/a/b/c/12345abcd.json'


def test_can_save(base_file_path, optimized_file_path):
    fss = get_filesystem_storage()
    fss.save(base_file_path, b'\x08Test')
    assert os.path.isfile(optimized_file_path)
    with open(optimized_file_path, 'rb') as fo:
        assert fo.read() == b'\x08Test'


def test_can_save_finalize(base_file_path, optimized_file_path):
    fss = get_filesystem_storage()
    fss.save(base_file_path, b'\x08Test', is_final=True)
    assert os_stat(optimized_file_path).st_mode & (stat.S_IWGRP | stat.S_IWUSR | stat.S_IWOTH) == 0


def test_can_finalize(base_file_path, optimized_file_path):
    fss = get_filesystem_storage()
    fss.save(base_file_path, b'\x08Test')
    assert os_stat(optimized_file_path).st_mode & (stat.S_IWGRP | stat.S_IWUSR | stat.S_IWOTH) != 0

    fss.finalize(base_file_path)
    assert os_stat(optimized_file_path).st_mode & (stat.S_IWGRP | stat.S_IWUSR | stat.S_IWOTH) == 0


def test_can_append(base_file_path, optimized_file_path):
    fss = get_filesystem_storage()
    fss.save(base_file_path, b'\x08Test')
    assert os.path.isfile(optimized_file_path)
    with open(optimized_file_path, 'rb') as fo:
        assert fo.read() == b'\x08Test'

    fss.append(base_file_path, b'\x09\x0aAPPEND')
    with open(optimized_file_path, 'rb') as fo:
        assert fo.read() == b'\x08Test\x09\x0aAPPEND'


def test_can_load(base_file_path, optimized_file_path):
    binary_data = b'\x08Test'

    fss = get_filesystem_storage()
    fss.save(base_file_path, binary_data)
    assert os.path.isfile(optimized_file_path)
    with open(optimized_file_path, 'rb') as fo:
        assert fo.read() == binary_data

    assert fss.load(base_file_path) == binary_data


def test_compression(base_file_path, optimized_file_path):
    binary_data = b'A' * 10000

    fss = get_filesystem_storage(compressors=('gz',))
    fss.save(base_file_path, binary_data, is_final=True)
    expected_path = optimized_file_path + '.gz'
    assert os.path.isfile(expected_path)

    with gzip.open(expected_path, 'rb') as fo:
        assert fo.read() == binary_data

    assert fss.load(base_file_path) == binary_data


def test_list_directory(blockchain_directory):
    base_directory = os.path.join(blockchain_directory, 'test')

    fss = get_filesystem_storage(compressors=('gz',))
    fss.save(os.path.join(base_directory, '1434567890.txt'), b'A' * 1000, is_final=True)
    fss.save(os.path.join(base_directory, '1134567890.txt'), b'test1')
    fss.save(os.path.join(base_directory, '1234567890.txt'), b'test2')
    fss.save(os.path.join(base_directory, '1334567890.txt'), b'test3')

    assert {
        os.path.join(base_directory, '1134567890.txt'),
        os.path.join(base_directory, '1234567890.txt'),
        os.path.join(base_directory, '1334567890.txt'),
        os.path.join(base_directory, '1434567890.txt'),
    } == set(fss.list_directory(base_directory))


@pytest.mark.parametrize(
    'sort_direction,expected', (
        (1, ('111/a.txt', '111/b.txt', '222/a.txt')),
        (-1, ('222/a.txt', '111/b.txt', '111/a.txt')),
    )
)
def test_can_list_directory_with_sorting(blockchain_path, sort_direction, expected):
    fss = FileSystemStorage()
    expected_absolute = [str(blockchain_path / rel_path) for rel_path in expected]

    mkdir_and_touch(blockchain_path / '111/a.txt')
    mkdir_and_touch(blockchain_path / '111/b.txt')
    mkdir_and_touch(blockchain_path / '222/a.txt')

    listed = list(fss.list_directory(blockchain_path, sort_direction=sort_direction))
    assert listed == expected_absolute


def test_can_list_directory_without_sorting(blockchain_path):
    fss = FileSystemStorage()

    mkdir_and_touch(blockchain_path / '111/a.txt')
    mkdir_and_touch(blockchain_path / '111/b.txt')
    mkdir_and_touch(blockchain_path / '222/a.txt')

    listed = fss.list_directory(blockchain_path, sort_direction=None)
    assert {
        str(blockchain_path / '111/a.txt'),
        str(blockchain_path / '111/b.txt'),
        str(blockchain_path / '222/a.txt'),
    } == set(listed)


@pytest.mark.parametrize('compression', ('gz', 'bz2', 'xz'))
def test_list_directory_strips_compression_extensions(blockchain_path, compression):
    fss = FileSystemStorage()

    mkdir_and_touch(blockchain_path / f'a.txt.{compression}')

    listed = list(fss.list_directory(blockchain_path))
    assert listed == [str(blockchain_path / 'a.txt')]


@pytest.mark.parametrize('compression', ('gz', 'bz2', 'xz'))
def test_can_load_compressed_file(blockchain_path, compression):
    fss = FileSystemStorage()
    compressed_path = blockchain_path / f'file.txt.{compression}'

    compress(compressed_path, compression, b'test data')

    loaded_data = fss.load(str(blockchain_path / 'file.txt'))
    assert loaded_data == b'test data'


@pytest.mark.parametrize('compression', ('gz', 'bz2', 'xz'))
def test_finalized_data_is_compressed(blockchain_path, compression, compressible_data):
    fss = FileSystemStorage(compressors=(compression,))
    file_path = blockchain_path / f'file.txt.{compression}'

    fss.save(str(blockchain_path / 'file.txt'), compressible_data, is_final=True)

    decompressed_data = decompress(file_path, compression)
    assert decompressed_data == compressible_data


@pytest.mark.parametrize('compression', ('gz', 'bz2', 'xz'))
def test_incompressible_data_is_saved_raw(blockchain_path, compression, incompressible_data):
    fss = FileSystemStorage()
    file_path = blockchain_path / 'incompressible_file.txt'

    fss.save(str(file_path), binary_data=incompressible_data, is_final=True)

    assert file_path.exists()
    assert file_path.read_bytes() == incompressible_data


def test_no_compression_file_storage_saves_raw_files(blockchain_path, compressible_data):
    fss = FileSystemStorage(compressors=())
    file_path = blockchain_path / 'file.txt'

    fss.save(str(file_path), binary_data=compressible_data, is_final=True)

    assert file_path.exists()
    assert file_path.read_bytes() == compressible_data


def test_save_to_raw_finalized_file_raises_error(blockchain_path, compressible_data):
    fss = FileSystemStorage(compressors=())
    file_path = str(blockchain_path / 'file.txt')

    fss.save(file_path, binary_data=compressible_data, is_final=True)

    with pytest.raises(exceptions.FinalizedFileWriteError):
        fss.save(file_path, compressible_data)
