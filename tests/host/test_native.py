import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from native_control import control, status, write_json
from snipping import region, png
import zlib
import struct


class NativeStatusTest(unittest.TestCase):
    def test_stale_or_old_registration_is_never_shown_as_connected(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)
            for value in ({'bindings':{'1':'Ctrl+Alt+I'}},
                          {'version':2,'heartbeat':time.time()-20,'bindings':{'1':'Ctrl+Alt+I'}}):
                write_json(data/'native-status.json',value)
                self.assertFalse(status(data)['running'])
                self.assertEqual(status(data)['bindings'],{})
            write_json(data/'native-status.json',{'version':2,'heartbeat':time.time(),'bindings':{'1':'Ctrl+Alt+I'},'test_until':time.time()+10})
            self.assertTrue(status(data)['running'])
            self.assertGreater(status(data)['test_remaining'],0)

    def test_unknown_native_action_cannot_launch_a_command(self):
        with tempfile.TemporaryDirectory() as tmp,patch('native_control.start') as start:
            with self.assertRaises(ValueError):
                control(Path(tmp),'run shell')
            start.assert_not_called()

    def test_transient_windows_sharing_violation_retries_without_losing_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'status.json'
            from os import replace
            attempts=[]
            def flaky(source,target):
                attempts.append(1)
                if len(attempts)<3: raise PermissionError('Windows sharing violation')
                replace(source,target)
            with patch('native_control.os.replace',side_effect=flaky),patch('native_control.time.sleep'):
                write_json(path,{'heartbeat':123})
            self.assertEqual(json.loads(path.read_text()),{'heartbeat':123})
            self.assertEqual(len(attempts),3)
            self.assertEqual(list(path.parent.glob('*.tmp')),[])

    def test_sustained_lock_cleans_temporary_files_and_next_write_can_recover(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'status.json'
            with patch('native_control.os.replace',side_effect=PermissionError('locked')),patch('native_control.time.sleep'):
                with self.assertRaises(PermissionError):write_json(path,{'heartbeat':1})
            self.assertEqual(list(path.parent.iterdir()),[])
            write_json(path,{'heartbeat':2})
            self.assertEqual(json.loads(path.read_text())['heartbeat'],2)

    def test_region_normalizes_reverse_drag_negative_monitors_and_bounds(self):
        desktop=(-1920,-100,3840,1180)
        self.assertEqual(region((-10,500),(-100,200),desktop),(-100,200,90,300))
        self.assertEqual(region((-2000,-500),(-1800,100),desktop),(-1920,-100,120,200))
        for a,b in [((1,1),(2,2)),((5000,1),(6000,100))]:
            with self.assertRaises(ValueError):region(a,b,desktop)

    def test_png_contains_only_selected_pixels_in_correct_color_order(self):
        encoded=png(2,1,bytes([0,0,255,0,255,0,0,0]))
        self.assertTrue(encoded.startswith(b'\x89PNG\r\n\x1a\n'))
        offset=8;compressed=b''
        while offset<len(encoded):
            size=struct.unpack('!I',encoded[offset:offset+4])[0]
            if encoded[offset+4:offset+8]==b'IDAT':compressed+=encoded[offset+8:offset+8+size]
            offset+=12+size
        self.assertEqual(zlib.decompress(compressed),b'\x00\xff\x00\x00\x00\x00\xff')
