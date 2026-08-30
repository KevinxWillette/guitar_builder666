# KILLETTE neck generator v4 — Killy's approved spec
# 7 woods x (straight + multiscale) = 14 necks, orthographic flat view,
# max 24 frets full-width, multiscale neutral at the 12th fret, slim true taper.
# Run: python3 neckgen4.py   (needs: pip install numpy pillow)
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import os

W, H = 170, 1400              # slim board, tall canvas
PPI = 52                      # px per inch along the neck
SCALE_TREBLE = 25.5           # inches (right side)
SCALE_BASS   = 27.0           # inches (left side) -> the fan
FRETS = 24

WOODS = {
 'mahogany':     ((134,70,44),(96,46,28),(60,28,16),0.55),
 'black-walnut': ((88,62,44),(56,38,26),(30,20,14),0.7),
 'maple':        ((228,205,160),(206,180,132),(178,152,106),0.35),
 'purpleheart':  ((118,54,108),(86,36,78),(52,20,46),0.5),
 'acacia':       ((172,120,62),(120,78,38),(70,44,20),0.85),
 'ebony':        ((36,31,28),(24,20,18),(12,10,9),0.35),
 'wenge':        ((70,52,36),(38,27,18),(16,11,8),1.0),
}

def wood_texture(c1, c2, c3, contrast, seed):
    rng = np.random.default_rng(seed)
    gx = rng.random((6, 90))
    g = np.array(Image.fromarray((gx*255).astype('uint8')).resize((W, H), Image.BICUBIC)) / 255.0
    yy = np.linspace(0, 12*np.pi, H)[:, None]
    wave = np.sin(yy + rng.random()*6) * 3
    idx = np.clip(np.arange(W)[None, :] + wave.astype(int), 0, W-1)
    g = np.take_along_axis(g, idx, axis=1)
    lines = (np.sin(g * np.pi * 7) + 1) / 2
    fine = rng.random((H//3, W//2))
    fine = np.array(Image.fromarray((fine*255).astype('uint8')).resize((W, H), Image.BICUBIC)) / 255.0
    t = np.clip(np.clip(0.75*lines + 0.25*fine, 0, 1) * contrast, 0, 1)
    c1, c2, c3 = np.array(c1), np.array(c2), np.array(c3)
    img = np.where(t[:,:,None] < 0.5,
                   c1[None,None,:]*(1-t[:,:,None]*2) + c2[None,None,:]*(t[:,:,None]*2),
                   c2[None,None,:]*(2-t[:,:,None]*2) + c3[None,None,:]*(t[:,:,None]*2-1))
    xs = np.linspace(-1, 1, W)[None, :, None]
    ys = np.linspace(0, 1, H)[:, None, None]
    img = img * (1 - 0.07*xs**2) * (0.93 + 0.09*(1-ys))   # near-flat ortho shading
    return np.clip(img, 0, 255).astype('uint8')

def fret_y(n, scale_in):
    # exact equal-temperament distance from the nut, in px
    return scale_in * (1 - 1/(2**(n/12))) * PPI

def make(wood, multiscale, seed):
    c1, c2, c3, contrast = WOODS[wood]
    im = Image.fromarray(wood_texture(c1, c2, c3, contrast, seed)).convert('RGBA')
    dr = ImageDraw.Draw(im)

    sL = SCALE_BASS if multiscale else SCALE_TREBLE
    sR = SCALE_TREBLE
    # align both sides at the 12th fret -> neutral / level fret at 12
    y12 = 30 + fret_y(12, max(sL, sR))
    yL = [y12 + (fret_y(n, sL) - fret_y(12, sL)) for n in range(0, FRETS+1)]
    yR = [y12 + (fret_y(n, sR) - fret_y(12, sR)) for n in range(0, FRETS+1)]
    end_y = max(yL[FRETS], yR[FRETS]) + 42       # short heel right after fret 24
    nut_top = min(yL[0], yR[0])

    top_w, bot_w = 0.72, 0.90                    # true ~43mm -> ~57mm taper
    def edge_x(y, side):
        t = (y - nut_top) / (end_y - nut_top)
        w = top_w + (bot_w - top_w) * t
        return W*(1-w)/2 if side == 'L' else W*(1+w)/2

    mask = Image.new('L', (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.polygon([(edge_x(nut_top,'L'), nut_top-16), (edge_x(nut_top,'R'), nut_top-16),
                (edge_x(end_y,'R'), end_y), (edge_x(end_y,'L'), end_y)], fill=255)

    # inlays first so fret wire draws on top; dots shrink as gaps tighten
    dots = {3:1,5:1,7:1,9:1,15:1,17:1,19:1,21:1,12:2,24:2}
    for n, k in dots.items():
        my = (yL[n-1]+yL[n]+yR[n-1]+yR[n]) / 4
        gap = ((yL[n]-yL[n-1]) + (yR[n]-yR[n-1])) / 2
        r = max(3, min(8, gap*0.26))
        cx = W/2
        off = W*0.13
        for j in range(k):
            ox = (-off if k == 2 else 0) + j*2*off
            dr.ellipse([cx+ox-r, my-r, cx+ox+r, my+r],
                       fill=(238,228,208,255), outline=(110,100,88,255), width=1)

    # frets 1..24, full width, fanned around the 12th on multiscale
    for n in range(1, FRETS+1):
        x0, x1 = edge_x(yL[n],'L'), edge_x(yR[n],'R')
        dr.line([x0, yL[n]+1, x1, yR[n]+1], fill=(35,35,40,190), width=2)
        dr.line([x0, yL[n],   x1, yR[n]],   fill=(208,210,216,255), width=3)

    # nut — slanted on multiscale, straight otherwise
    nut = [(edge_x(yL[0],'L')-2, yL[0]-16), (edge_x(yR[0],'R')+2, yR[0]-16),
           (edge_x(yR[0],'R')+2, yR[0]),    (edge_x(yL[0],'L')-2, yL[0])]
    dr.polygon(nut, fill=(240,234,216,255))
    dr.line([nut[3], nut[2]], fill=(178,170,148,255), width=3)

    gl = Image.new('RGBA', (W, H), (0,0,0,0))
    gd = ImageDraw.Draw(gl)
    gd.polygon([(W*0.30,0),(W*0.41,0),(W*0.33,H),(W*0.22,H)], fill=(255,255,255,24))
    im = Image.alpha_composite(im, gl.filter(ImageFilter.GaussianBlur(7)))
    im.putalpha(mask)
    return im.crop(im.getbbox())

if __name__ == '__main__':
    out = 'necks_v4'
    os.makedirs(out, exist_ok=True)
    i = 0
    for wood in WOODS:
        for ms in (False, True):
            i += 1
            img = make(wood, ms, seed=i*13)
            tag = 'multiscale' if ms else 'straight'
            p = f"{out}/neck-{wood}-{tag}.png"
            img.save(p)
            t = img.copy(); t.thumbnail((160,160)); t.save(p.replace('.png','.thumb.png'))
    print("generated", i, "necks ->", out)
