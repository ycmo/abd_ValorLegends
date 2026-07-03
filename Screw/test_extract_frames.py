import unittest
import os
import shutil
import cv2
import numpy as np
from Screw.extract_frames import extract_frames_from_video

class TestExtractFrames(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.dirname(os.path.abspath(__file__))
        self.output_dir = os.path.join(self.test_dir, "test_frames")
        self.test_video_path = os.path.join(self.test_dir, "test_video.mp4")
        
        # Create a dummy video (12 frames, 5 fps)
        if os.path.exists(self.test_video_path):
            os.remove(self.test_video_path)
            
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(self.test_video_path, fourcc, 5.0, (100, 100))
        for i in range(12): 
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            frame[:] = (i * 20, i * 20, i * 20)
            out.write(frame)
        out.release()

    def tearDown(self):
        if os.path.exists(self.test_video_path):
            os.remove(self.test_video_path)
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)

    def test_extract_frames_from_video(self):
        result = extract_frames_from_video(self.test_video_path, self.output_dir)
        self.assertTrue(result)
        
        self.assertTrue(os.path.exists(self.output_dir))
        frames = os.listdir(self.output_dir)
        
        # 12 frames at 5 FPS:
        # frame 0, 5, 10 -> 3 frames extracted
        self.assertEqual(len(frames), 3)
        self.assertIn("test_video_frame_0000.jpg", frames)
        self.assertIn("test_video_frame_0001.jpg", frames)
        self.assertIn("test_video_frame_0002.jpg", frames)

if __name__ == "__main__":
    unittest.main()
