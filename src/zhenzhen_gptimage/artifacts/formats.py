"""Bounded validation of animated GIF and passive SVG originals."""
from __future__ import annotations
from io import BytesIO
import math
import re
from xml.etree import ElementTree
from PIL import Image

SVG_BYTES = 8 * 1024 * 1024
GIF_TOTAL_PIXELS = 33_554_432
SVG_TAGS = {'svg','g','path','rect','circle','ellipse','line','polyline','polygon',
            'defs','linearGradient','radialGradient','stop','clipPath','title','desc'}
SVG_ATTRS = {'width','height','viewBox','x','y','x1','y1','x2','y2','cx','cy','r','rx','ry',
             'd','points','fill','fill-opacity','fill-rule','stroke','stroke-width','stroke-opacity',
             'stroke-linecap','stroke-linejoin','stroke-miterlimit','opacity','transform','id',
             'clip-path','offset','stop-color','stop-opacity','gradientUnits','gradientTransform',
             'version','preserveAspectRatio','role','aria-label','aria-labelledby','aria-describedby'}
SVG_NS = 'http://www.w3.org/2000/svg'

def inspect_svg(data: bytes) -> tuple[int,int,dict]:
    if len(data)>SVG_BYTES: raise ValueError('SVG file exceeds limit')
    try:
        text=data.decode('utf-8-sig')
    except UnicodeError as exc: raise ValueError('SVG must be UTF-8') from exc
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('SVG declarations are not permitted')
    try: root=ElementTree.fromstring(text)
    except ElementTree.ParseError as exc: raise ValueError('invalid SVG XML') from exc
    if root.tag not in ('svg',f'{{{SVG_NS}}}svg'): raise ValueError('not SVG')
    stack=[(root,1)]; count=0
    while stack:
        elem,depth=stack.pop();count+=1
        if depth>128 or count>100000: raise ValueError('SVG complexity limit exceeded')
        if elem.tag.startswith('{') and not elem.tag.startswith(f'{{{SVG_NS}}}'):
            raise ValueError('unsupported SVG namespace')
        if elem.tag.rsplit('}',1)[-1] not in SVG_TAGS: raise ValueError('unsupported SVG element')
        for name,value in elem.attrib.items():
            if name not in SVG_ATTRS: raise ValueError('unsupported SVG attribute')
            lower=value.lower()
            if 'url(' in lower and not re.fullmatch(r'url\(\s*#[A-Za-z_][\w.-]*\s*\)',value):
                raise ValueError('SVG external reference')
            if any(x in lower for x in ('javascript:', 'data:', 'http:', 'https:', '@import', '\\')):
                raise ValueError('SVG external content')
        stack.extend((child,depth+1) for child in elem)
    def dimension(value):
        if value is None: return None
        match=re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*',value)
        return float(match.group(1)) if match else None
    width=dimension(root.get('width'));height=dimension(root.get('height'))
    if width is None or height is None:
        try:
            view=[float(v) for v in re.split(r'[\s,]+',root.get('viewBox','').strip())]
            if len(view)!=4: raise ValueError
            width,height=view[2],view[3]
        except ValueError as exc: raise ValueError('SVG canvas dimensions unavailable') from exc
    if not (math.isfinite(width) and math.isfinite(height) and width>0 and height>0 and width.is_integer() and height.is_integer() and max(width,height)<=4096 and width*height<=16_777_216):
        raise ValueError('invalid SVG canvas')
    return int(width),int(height),{}

def inspect_gif(data: bytes) -> tuple[int,int,dict]:
    with Image.open(BytesIO(data)) as image:
        if image.format != 'GIF': raise ValueError('not a GIF')
        w,h=image.size; frames=getattr(image,'n_frames',1)
        if not (2<=frames<=16 and 0<w<=4096 and 0<h<=4096 and w*h<=8_294_400 and w*h*frames<=GIF_TOTAL_PIXELS):
            raise ValueError('GIF animation limits exceeded')
        durations=[]; loop=image.info.get('loop')
        for i in range(frames):
            image.seek(i);image.load();duration=image.info.get('duration')
            if not isinstance(duration,int) or duration<=0: raise ValueError('GIF duration missing')
            durations.append(duration)
        return w,h,{'frame_count':frames,'durations_ms':durations,'loop':loop}
