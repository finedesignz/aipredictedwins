import struct, os

def make_ico(path, size=32):
    W = H = size

    # BGRA: dark bg (#0f1117) and blue accent (#3b82f6)
    bg = (23, 17, 15, 255)
    fg = (246, 130, 59, 255)

    pixels = []
    for y in range(H):
        row = []
        for x in range(W):
            if x < 2 or x > W - 3:
                row.append(bg)
                continue
            # upward-trending line
            ey = (H - 4) - (H - 8) * (x - 2) / (W - 5)
            row.append(fg if abs(y - ey) < 1.8 else bg)
        pixels.append(row)

    # 32-bit BMP INFOHEADER
    info = struct.pack('<IiiHHIIiiII', 40, W, H * 2, 1, 32, 0, W * H * 4, 0, 0, 0, 0)
    pd = b''.join(bytes(p) for row in reversed(pixels) for p in row)
    mask = b'\x00' * (((W + 31) // 32) * 4 * H)
    bmp = info + pd + mask

    hdr = struct.pack('<HHH', 0, 1, 1)
    dirent = struct.pack('<BBBBHHII', W & 0xFF, H & 0xFF, 0, 0, 1, 32, len(bmp), 22)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(hdr + dirent + bmp)
    print(f'Created {path} ({os.path.getsize(path)} bytes)')

make_ico('dashboard/web/public/favicon.ico')
