import cv2
import os
import glob

def extract_frames_from_video(video_path, output_dir):
    """
    Extracts one frame per second from the given video and saves them to the output directory.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    video_name = os.path.splitext(os.path.basename(video_path))[0]
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"Error: Cannot open video {video_path}")
        return False

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or fps is None or not (fps > 0):
        print(f"Error: Cannot determine FPS for {video_path}")
        return False

    # Extract 1 frame per second
    frame_interval = int(round(fps))
    if frame_interval <= 0:
        frame_interval = 1

    frame_count = 0
    saved_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        if frame_count % frame_interval == 0:
            output_path = os.path.join(output_dir, f"{video_name}_frame_{saved_count:04d}.jpg")
            cv2.imwrite(output_path, frame)
            saved_count += 1
            
        frame_count += 1

    cap.release()
    print(f"Successfully extracted {saved_count} frames from {video_name}")
    return True

def main():
    target_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(target_dir, "frames")
    
    mp4_files = glob.glob(os.path.join(target_dir, "*.mp4"))
    
    if not mp4_files:
        print("No .mp4 files found in the directory.")
        return

    for video_path in mp4_files:
        print(f"Processing {video_path}...")
        extract_frames_from_video(video_path, output_dir)

if __name__ == "__main__":
    main()
