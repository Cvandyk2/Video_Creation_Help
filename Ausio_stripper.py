#!/usr/bin/env python3
"""
Audio Stripper - Extract audio from video files
Supports various input formats (mp4, mov, avi, mkv, etc.)
and output formats (mp3, wav, aac, flac, ogg)
"""

import argparse
import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

try:
    from moviepy import VideoFileClip
except ImportError as e:
    print(f"Error: Cannot import moviepy: {e}")
    print(f"\nPython executable: {sys.executable}")
    print(f"Python version: {sys.version}")
    print("\nTry installing moviepy for this Python interpreter:")
    print(f"  {sys.executable} -m pip install moviepy")
    sys.exit(1)


def select_files_gui():
    """
    Open a file picker dialog to select video file(s).
    
    Returns:
        list: List of selected file paths, or empty list if cancelled
    """
    # Hide the root tkinter window
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    print("Opening file picker...")
    
    file_paths = filedialog.askopenfilenames(
        title="Select video file(s) to extract audio from",
        filetypes=[
            ("Video files", "*.mp4 *.mov *.avi *.mkv *.flv *.wmv *.webm *.m4v"),
            ("MP4 files", "*.mp4"),
            ("MOV files", "*.mov"),
            ("All files", "*.*")
        ]
    )
    
    root.destroy()
    
    return list(file_paths) if file_paths else []


def extract_audio(input_file, output_file=None, output_format="mp3", bitrate="192k"):
    """
    Extract audio from a video file and save it as a separate audio file.
    
    Args:
        input_file (str): Path to the input video file
        output_file (str): Path to the output audio file (optional)
        output_format (str): Audio format (mp3, wav, aac, flac, ogg)
        bitrate (str): Audio bitrate for lossy formats (e.g., "192k", "320k")
    
    Returns:
        str: Path to the output audio file
    """
    input_path = Path(input_file)
    
    # Check if input file exists
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    
    # Generate output filename if not provided
    if output_file is None:
        output_file = input_path.stem + f"_audio.{output_format}"
        output_path = input_path.parent / output_file
    else:
        output_path = Path(output_file)
    
    print(f"Extracting audio from: {input_file}")
    print(f"Output file: {output_path}")
    
    try:
        # Load the video file
        video = VideoFileClip(str(input_path))
        
        # Check if video has audio
        if video.audio is None:
            video.close()
            raise ValueError("The video file has no audio track")
        
        # Extract and save audio
        audio = video.audio
        
        # Save with appropriate parameters based on format
        if output_format in ["mp3", "aac", "ogg"]:
            audio.write_audiofile(
                str(output_path),
                bitrate=bitrate
            )
        else:
            audio.write_audiofile(
                str(output_path)
            )
        
        # Clean up
        audio.close()
        video.close()
        
        print(f"✓ Audio extracted successfully: {output_path}")
        return str(output_path)
        
    except Exception as e:
        print(f"Error extracting audio: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Extract audio from video files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Open file picker (no arguments)
  python Audio_Stripper.py
  
  # Extract audio as MP3 (default)
  python Audio_Stripper.py video.mp4
  
  # Extract audio as WAV with custom output name
  python Audio_Stripper.py video.mp4 -o output.wav
  
  # Extract audio as MP3 with high quality
  python Audio_Stripper.py video.mp4 -f mp3 -b 320k
  
  # Process multiple files
  python Audio_Stripper.py video1.mp4 video2.mov video3.avi
        """
    )
    
    parser.add_argument(
        "input_files",
        nargs="*",  # Changed from "+" to "*" to make it optional
        help="Input video file(s). If omitted, a file picker will open."
    )
    
    parser.add_argument(
        "-o", "--output",
        help="Output audio file (only works with single input file)"
    )
    
    parser.add_argument(
        "-f", "--format",
        choices=["mp3", "wav", "aac", "flac", "ogg"],
        default="mp3",
        help="Output audio format (default: mp3)"
    )
    
    parser.add_argument(
        "-b", "--bitrate",
        default="192k",
        help="Audio bitrate for lossy formats (default: 192k)"
    )
    
    parser.add_argument(
        "-g", "--gui",
        action="store_true",
        help="Force open file picker dialog"
    )
    
    args = parser.parse_args()
    
    # If no input files provided or --gui flag used, open file picker
    if not args.input_files or args.gui:
        selected_files = select_files_gui()
        if not selected_files:
            print("No files selected. Exiting.")
            sys.exit(0)
        args.input_files = selected_files
    
    # Check if output file is specified with multiple inputs
    if args.output and len(args.input_files) > 1:
        print("Error: Cannot specify output file with multiple input files")
        sys.exit(1)
    
    success_count = 0
    fail_count = 0
    
    for input_file in args.input_files:
        try:
            extract_audio(
                input_file,
                output_file=args.output,
                output_format=args.format,
                bitrate=args.bitrate
            )
            success_count += 1
        except Exception as e:
            print(f"Failed to process {input_file}: {e}")
            fail_count += 1
        print()  # Empty line between files
    
    # Print summary if multiple files
    if len(args.input_files) > 1:
        print(f"Summary: {success_count} succeeded, {fail_count} failed")
    
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
