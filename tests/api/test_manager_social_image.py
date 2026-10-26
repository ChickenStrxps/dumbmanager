import base64
import hashlib
import io
import json
import os
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.app import App
from dumbapi_core.common import APIError, Config
from dumbapi_core.manager_media import Media
from dumbapi_core.manager import Manager
from dumbapi_core.manager_social_image import FULL, render, rectangles

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ZkAAAAASUVORK5CYII=')


def fixture(path):
    """Local synthetic work screen, with known text and a non-text private patch."""
    script=path.with_suffix('.ps1')
    script.write_text('''param([string]$Output)
Add-Type -AssemblyName System.Drawing
$b=[Drawing.Bitmap]::new(1000,625);$g=[Drawing.Graphics]::FromImage($b)
$g.Clear([Drawing.Color]::FromArgb(14,14,22))
$f=[Drawing.Font]::new('Arial',30)
$g.DrawString('SECRET PROJECT ALPHA',$f,[Drawing.Brushes]::White,35,25)
$g.DrawString('person@example.com',$f,[Drawing.Brushes]::White,35,85)
$g.FillRectangle([Drawing.Brushes]::HotPink,100,225,750,270)
$g.FillEllipse([Drawing.Brushes]::Cyan,440,270,180,180)
for($x=50;$x -lt 300;$x+=10){$g.FillRectangle([Drawing.Brushes]::Red,$x,540,5,45)}
$b.Save($Output,[Drawing.Imaging.ImageFormat]::Png)
$f.Dispose();$g.Dispose();$b.Dispose()
''',encoding='utf-8')
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(script),str(path)],check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return path


class SocialImageTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.app=App(Config(self.root,self.root/'data'))
        self.manager=Manager(self.app.config);self.media=Media(self.manager)
        self.row=self.app.call('manager.capture',{'title':'The result fits now','project':'secret-project','use_active':False})
        self.row=self.app.call('manager.update',{'id':self.row['id'],'changes':json.dumps({'state':'ready'})})
        self.draft=self.app.call('manager.social.draft',{'itch_id':self.row['id']})

    def upload(self,data=PNG):
        return self.media.upload(self.app.config,io.BytesIO(data),len(data),'work.png','image/png')['attachment']

    def image(self,**args):
        return self.app.call('manager.social.image',{'id':self.draft['id'],'expected_version':self.draft['version'],**args})

    def fake(self,source,destination,crop,masks):
        destination.write_bytes(PNG)
        return {'automatic_regions':1,'boxes':[{'x':0,'y':0,'width':.2,'height':.2}],'width':640,'height':400}

    @patch('dumbapi_core.manager_social_image.render')
    def test_saved_receipt_auto_picture_and_exact_review(self,mocked):
        mocked.side_effect=self.fake;a=self.upload()
        self.app.call('manager.attach',{'id':self.row['id'],'attachments':json.dumps([a['id']])})
        p=self.app.call('manager.social.preview',{'id':self.draft['id']});d=p['draft']
        self.assertTrue(p['export_ready']);self.assertIn('<image ',p['svg'])  # no manual picture check;self.assertNotIn('secret-project',p['svg'])
        self.assertEqual(d['image']['source']['id'],a['id']);self.assertNotIn('file',d['image'])
        with self.assertRaises(APIError):self.app.call('manager.social.image_review',{'id':d['id'],'expected_version':d['version'],'digest':'0'*64})
        reviewed=self.app.call('manager.social.image_review',{'id':d['id'],'expected_version':d['version'],'digest':d['image']['digest']})
        self.assertTrue(self.app.call('manager.social.preview',{'id':d['id']})['export_ready'])
        current=self.app.call('manager.get',{'id':self.row['id']});self.assertEqual(current['state'],'ready');self.assertEqual(current['outcomes'],[])
        self.assertTrue(reviewed['source_changed'])  # Image review does not silently review changed copy.

    @patch('dumbapi_core.manager_social_image.render')
    def test_mask_change_invalidates_review_and_failed_processing_keeps_previous(self,mocked):
        mocked.side_effect=self.fake;a=self.upload();self.draft=self.image(attachment_id=a['id'])
        old=self.draft
        with patch('dumbapi_core.manager_social_image.render',side_effect=APIError('OCR offline')):
            with self.assertRaises(APIError):self.image(attachment_id=a['id'])
        self.assertEqual(self.app.call('manager.social.draft',{'itch_id':self.row['id']})['version'],old['version'])
        self.draft=self.image(attachment_id=a['id'],masks='[{"x":0.2,"y":0.2,"width":0.3,"height":0.3}]')
        self.assertFalse(self.draft['image']['reviewed']);self.assertEqual(self.draft['image']['masks'][0]['width'],.3)
        self.assertEqual(self.media.read(a['id'])[0].read_bytes(),PNG)
        with self.assertRaises(APIError):self.app.call('manager.social.image_review',{'id':old['id'],'expected_version':old['version'],'digest':old['image']['digest']})

    @patch('dumbapi_core.manager_social_image.render')
    def test_stale_or_reopened_work_cannot_overwrite_and_opt_out_persists(self,mocked):
        a=self.upload()
        def concurrent(*args):
            self.app.call('manager.social.save',{'id':self.draft['id'],'expected_version':self.draft['version'],'headline':'New copy','summary':'Still testing','caption':'Keep my copy'})
            return self.fake(*args)
        mocked.side_effect=concurrent
        with self.assertRaises(APIError):self.image(attachment_id=a['id'])
        self.draft=self.app.call('manager.social.draft',{'itch_id':self.row['id']})
        self.assertEqual(self.draft['caption'],'Keep my copy');self.assertFalse(self.draft.get('image'))
        def reopen(*args):
            self.app.call('manager.update',{'id':self.row['id'],'changes':'{"state":"working"}'})
            return self.fake(*args)
        mocked.side_effect=reopen
        with self.assertRaises(APIError):self.image(attachment_id=a['id'])
        self.app.call('manager.update',{'id':self.row['id'],'changes':'{"state":"ready"}'})
        self.app.call('manager.attach',{'id':self.row['id'],'attachments':json.dumps([a['id']])})
        self.draft=self.image(source='none')
        p=self.app.call('manager.social.preview',{'id':self.draft['id']})
        self.assertTrue(p['export_ready']);self.assertNotIn('<image ',p['svg'])

    @staticmethod
    def png(width,height):
        import zlib
        chunk=lambda kind,data:struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        rows=b''.join(bytes(1)+bytes([64])*width for _ in range(height))
        return bytes([0x89])+b'PNG'+bytes([13,10,26,10])+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,0,0,0,0))+chunk(b'IDAT',zlib.compress(rows,9))+chunk(b'IEND',b'')

    @patch('dumbapi_core.manager_social_image.render')
    def test_saved_review_evidence_screenshot_becomes_the_proof_picture(self,mocked):
        mocked.side_effect=self.fake
        root=self.manager.data/'review-evidence';own=root/self.row['id'];own.mkdir(parents=True)
        (own/'phone-390.png').write_bytes(self.png(390,844));(own/'live-desktop.png').write_bytes(self.png(1366,768))
        outside=self.root/'elsewhere';outside.mkdir();(outside/'desktop-huge.png').write_bytes(self.png(1600,900))
        self.app.call('manager.update',{'id':self.row['id'],'changes':json.dumps({'evidence':['Evidence: '+str(outside),'Shots: '+str(own)]})})
        p=self.app.call('manager.social.preview',{'id':self.draft['id']})
        self.assertEqual(p['draft']['image']['source']['name'],'proof-live-desktop.png');self.assertIn('<image ',p['svg'])
        self.assertTrue(p['export_ready'])
        self.assertTrue((own/'live-desktop.png').is_file())  # the saved evidence itself is untouched
        # Text only is respected; the evidence shot is not re-added.
        d=self.app.call('manager.social.image',{'id':self.draft['id'],'expected_version':p['draft']['version'],'source':'none'})
        self.assertIsNone(self.app.call('manager.social.preview',{'id':d['id']})['draft']['image'])

    @patch('dumbapi_core.manager_social_image.render',side_effect=APIError('ocr down','image_unavailable',503))
    def test_unprocessable_evidence_screenshot_still_gives_a_card(self,mocked):
        own=self.manager.data/'review-evidence'/self.row['id'];own.mkdir(parents=True);(own/'desktop.png').write_bytes(self.png(1200,700))
        p=self.app.call('manager.social.preview',{'id':self.draft['id']})
        self.assertIsNone(p['draft']['image']);self.assertNotIn('<image ',p['svg'])

    def test_rectangles_and_non_image_rejected(self):
        for value in ('null','{}','[{}]','[{"x":NaN,"y":0,"width":1,"height":1}]',json.dumps([FULL]*33)):
            with self.assertRaises(APIError):rectangles(value)
        with self.assertRaises(APIError):rectangles('{"x":0.9,"y":0,"width":0.5,"height":1}',True)
        self.assertEqual(rectangles(json.dumps(FULL),True),FULL)
        a=self.media.upload(self.app.config,io.BytesIO(b'video'),5,'work.mp4','video/mp4')['attachment']
        with self.assertRaises(APIError):self.image(attachment_id=a['id'])

    @patch('dumbapi_core.manager_social_image.render')
    def test_capture_only_current_owned_browser_and_tampered_artifact_blocked(self,mocked):
        mocked.side_effect=self.fake
        with patch('dumbapi_core.browser.instance') as browser:
            browser.return_value.snapshot.return_value={'image':base64.b64encode(PNG).decode()}
            self.draft=self.image(source='browser');browser.return_value.snapshot.assert_called_once_with()
        self.assertEqual(self.draft['image']['source']['name'],'work-screenshot.jpg')
        raw=self.app.call('manager.get',{'id':self.draft['id']})
        path=self.manager.data/'social-images'/raw['image']['file'];path.write_bytes(b'changed')
        with self.assertRaises(APIError):self.app.call('manager.social.preview',{'id':self.draft['id']})

    @unittest.skipUnless(os.name=='nt','Windows local OCR')
    def test_real_local_ocr_and_manual_masks_flatten_without_original_metadata(self):
        source=fixture(self.root/'source.png');original=source.read_bytes()
        safe=self.root/'safe.png';details=render(source,safe,FULL,[{'x':.04,'y':.85,'width':.28,'height':.1}])
        self.assertGreater(details['automatic_regions'],3)
        self.assertEqual(struct.unpack('>II',safe.read_bytes()[16:24]),(1280,800))
        self.assertEqual(source.read_bytes(),original);self.assertNotEqual(safe.read_bytes(),original)
        self.assertNotIn(b'person@example.com',safe.read_bytes())
        self.assertNotIn(b'SECRET',json.dumps(details).encode())
        # Read actual flattened pixels with Windows drawing, independently of OCR.
        check=self.root/'pixels.ps1'
        check.write_text('''param([string]$Image)
Add-Type -AssemblyName System.Drawing
$b=[Drawing.Bitmap]::FromFile($Image)
$same=$true;$first=$b.GetPixel(80,700).ToArgb()
for($x=80;$x -lt 350;$x++){if($b.GetPixel($x,700).ToArgb() -ne $first){$same=$false}}
$work=$b.GetPixel(640,440);$b.Dispose()
@{masked=$same;work_visible=($work.G -gt 200 -and $work.B -gt 200)}|ConvertTo-Json -Compress
''',encoding='utf-8')
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(check),str(safe)],capture_output=True,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        pixels=json.loads(result.stdout);self.assertTrue(pixels['masked']);self.assertTrue(pixels['work_visible'])


if __name__=='__main__':unittest.main()
