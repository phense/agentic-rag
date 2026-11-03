"""Child-process decoder for image_media._decode; never imported by the service.

Exit codes: 0 decoded (one JSON line), 2 malformed, 3 too many pixels,
4 Pillow unavailable, 6 resources exhausted. Output contains no pixel data.
"""
import json
import sys
import warnings


def main(argv):
    path, max_pixels = argv[1], int(argv[2])
    try:
        from PIL import Image, ImageFile
    except ImportError:
        return 4
    Image.MAX_IMAGE_PIXELS = max_pixels
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    try:
        with Image.open(path, formats=['PNG', 'JPEG', 'WEBP']) as image:
            fmt, size = image.format, image.size
            frames = getattr(image, 'n_frames', 1)
            if getattr(image, 'is_animated', False):
                frames = max(frames, 2)
            image.verify()  # PNG chunk CRCs and structure
        with Image.open(path, formats=['PNG', 'JPEG', 'WEBP']) as image:
            image.load()  # complete pixel decoding of the first (only) frame
            if image.size != size:
                return 2
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return 3
    except MemoryError:
        return 6
    except Exception:  # noqa: BLE001 - every decoder failure is one bounded outcome
        return 2
    print(json.dumps({'format': fmt, 'width': size[0], 'height': size[1], 'frames': frames}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
