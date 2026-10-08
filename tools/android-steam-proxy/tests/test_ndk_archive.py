"""CI controller extraction must preserve executable compiler symlinks."""
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'scripts/release'))
from ndk_archive import extract

class NdkExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cache=Path(self.temp.name);self.archive=self.cache/'ndk.zip'
    def make(self,link='clang-21',extra=None):
        with zipfile.ZipFile(self.archive,'w') as z:
            for name,raw,mode in [('ndk/',b'',stat.S_IFDIR|0o755),('ndk/bin/',b'',stat.S_IFDIR|0o755),
                ('ndk/bin/clang-21',b'compiler fixture',stat.S_IFREG|0o755),('ndk/bin/clang',link.encode(),stat.S_IFLNK|0o777)]:
                i=zipfile.ZipInfo(name);i.external_attr=mode<<16;z.writestr(i,raw)
            if extra:z.writestr(extra,b'bad')
    def test_compiler_symlink_and_executable_mode_preserved(self):
        self.make();root=extract(self.archive,self.cache,'ndk')
        self.assertTrue((root/'bin/clang').is_symlink());self.assertEqual((root/'bin/clang').read_bytes(),b'compiler fixture')
        self.assertEqual((root/'bin/clang-21').stat().st_mode&0o777,0o755)
    def test_existing_cache_verified_and_reused(self):
        self.make();root=extract(self.archive,self.cache,'ndk');self.assertEqual(extract(self.archive,self.cache,'ndk'),root)
    def test_relative_cache_can_be_created_and_rechecked(self):
        import os
        self.make();relative=Path(os.path.relpath(self.cache))
        root=extract(self.archive,relative,'ndk');self.assertEqual(extract(self.archive,relative,'ndk'),root)
    def test_changed_cached_compiler_rejected(self):
        self.make();root=extract(self.archive,self.cache,'ndk');(root/'bin/clang-21').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):extract(self.archive,self.cache,'ndk')
    def test_plain_file_instead_of_symlink_rejected(self):
        self.make();root=extract(self.archive,self.cache,'ndk');(root/'bin/clang').unlink();(root/'bin/clang').write_text('clang-21')
        with self.assertRaisesRegex(ValueError,'symlink mismatch'):extract(self.archive,self.cache,'ndk')
    def test_escape_link_rejected_without_partial_root(self):
        self.make('../../outside')
        with self.assertRaisesRegex(ValueError,'escapes'):extract(self.archive,self.cache,'ndk')
        self.assertFalse((self.cache/'ndk').exists())
    def test_absolute_link_rejected(self):
        self.make('/outside')
        with self.assertRaisesRegex(ValueError,'Unsafe'):extract(self.archive,self.cache,'ndk')
    def test_member_path_traversal_rejected(self):
        self.make(extra='../outside')
        with self.assertRaisesRegex(ValueError,'Unsafe'):extract(self.archive,self.cache,'ndk')
    def test_extra_cached_file_rejected(self):
        self.make();root=extract(self.archive,self.cache,'ndk');(root/'secret.key').write_text('never use')
        with self.assertRaisesRegex(ValueError,'Unexpected'):extract(self.archive,self.cache,'ndk')
