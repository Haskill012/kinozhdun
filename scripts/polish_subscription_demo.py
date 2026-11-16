"""Camera moves, click annotations and transitions over real browser footage."""
import json
import math
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'diagnostics/hero-demo/v2'
FF = ROOT / 'output/social-pilot-2026-10-07/tooling/imageio_ffmpeg/binaries/ffmpeg.exe'
FPS = 30
SIZE = (1280, 800)
LIME = (212, 250, 88)
FONT = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 38)
SMALL = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 23)
TINY = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 18)


def ease(t):
    t = max(0, min(1, t))
    return t*t*(3-2*t)


def pointer(frame, x, y, click_age=None):
    layer = Image.new('RGBA', frame.size)
    draw = ImageDraw.Draw(layer)
    if click_age is not None and 0 <= click_age < .55:
        t = click_age/.55
        radius = 14+ease(t)*32
        draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                     fill=(*LIME, round(36*(1-t))), outline=(*LIME, round(255*(1-t))), width=4)
    draw.ellipse((x-17, y-17, x+17, y+17), fill=(*LIME, 30))
    points = [(x+2,y+2),(x+2,y+32),(x+10,y+25),(x+18,y+40),(x+26,y+36),(x+19,y+23),(x+31,y+21)]
    draw.polygon(points,fill='white',outline='#111312',width=2)
    return Image.alpha_composite(frame.convert('RGBA'),layer).convert('RGB')


def backdrop():
    im = Image.new('RGB',SIZE)
    pixels=im.load()
    for y in range(SIZE[1]):
        for x in range(SIZE[0]):
            glow=max(0,1-math.hypot((x-1180)/1250,(y-60)/800))
            pixels[x,y]=(round(15+10*glow),round(20+17*glow),round(17+5*glow))
    return im


BACKGROUND = backdrop()


def compose(frame, rect, title, detail, step, progress):
    canvas = BACKGROUND.copy()
    crop = frame.crop(tuple(round(v) for v in (rect[0],rect[1],rect[0]+rect[2],rect[1]+rect[3])))
    if abs(crop.width/crop.height - 1152/600) > .005:
        scale = min(1152/crop.width,600/crop.height)
        strip = crop.resize((round(crop.width*scale), round(crop.height*scale)),Image.Resampling.LANCZOS)
        crop = Image.new('RGB',(1152,600),'#202b21')
        crop.paste(strip,((1152-strip.width)//2,(600-strip.height)//2))
    else:
        crop = crop.resize((1152,600),Image.Resampling.LANCZOS)
    mask=Image.new('L',crop.size);ImageDraw.Draw(mask).rounded_rectangle((0,0,1151,599),radius=20,fill=255)
    shadow=Image.new('RGBA',SIZE);sd=ImageDraw.Draw(shadow)
    sd.rounded_rectangle((62,169,1218,775),radius=23,fill=(0,0,0,100))
    canvas=Image.alpha_composite(canvas.convert('RGBA'),shadow.filter(ImageFilter.GaussianBlur(13))).convert('RGB')
    canvas.paste(crop,(64,158),mask)
    d=ImageDraw.Draw(canvas)
    d.rounded_rectangle((64,34,164,65),radius=15,fill=LIME)
    d.text((79,40), 'ГОТОВО' if step==4 else f'ШАГ {step}',font=TINY,fill='#111312')
    d.text((64,77),title,font=FONT,fill='#f4f4ec')
    d.text((65,123),detail,font=SMALL,fill='#b5c0ac')
    d.text((1052,44),'КИНОЖДУН',font=TINY,fill=LIME)
    for i in range(3):
        d.rounded_rectangle((64+i*42,777,91+i*42,782),radius=2,fill=LIME if i<min(step,3) else '#3b4635')
    d.line((205,779,1216,779),fill='#35402f',width=3)
    d.line((205,779,205+1011*progress,779),fill=LIME,width=3)
    return canvas


def render(scenes=None, target=None, output=None, frame_editor=None, blend_frames=8, transition_shift=46):
    output = output or OUT
    if scenes is None:
      capture=json.loads((OUT/'capture.json').read_text(encoding='utf-8'))
      site=Path(capture['source'])
      telegram=ROOT/'diagnostics/hero-demo/raw/page@deb8f3d6e38887b206dd179301b21202.webm'
      scenes=[
      {'source':site,'size':(1280,1000),'start':3.65,'source_duration':5.0,'speed':1.16,
       'from':(0,0,1264,658),'to':(330,0,880,458),'zoom_start':.15,'zoom_end':1.8,
       'title':'Выберите фильм','detail':'Найдите новинку на КиноЖдуне','step':1},
      {'source':site,'size':(1280,1000),'start':11.1,'source_duration':4.85,'speed':1.3,
       'from':(0,185,1264,658),'to':(270,402,820,427),'zoom_start':.45,'zoom_end':2.1,
       'title':'Откройте Telegram','detail':'«Ждать премьеру» → Telegram','step':2},
      {'source':telegram,'size':(1280,800),'start':97.0,'source_duration':2.5,'speed':1,
       'from':(485,350,550,286),'to':(510,410,490,255),'zoom_start':.1,'zoom_end':1.15,
       'title':'Подтвердите подписку','detail':'Нажмите «Ждать премьеру» в боте','step':3,'cursor':True},
      {'source':telegram,'size':(1280,800),'start':100,'source_duration':3.8,'speed':1,
       'from':(500,473,500,260),'to':(510,485,470,245),'zoom_start':0,'zoom_end':2.3,
       'title':'Готово! КиноЖдун напомнит','detail':'Фильм сохранён в вашем списке ожидания','step':4},
    ]
    total_frames=sum(round(s['source_duration']/s['speed']*FPS) for s in scenes)-blend_frames*(len(scenes)-1)
    target=target or ROOT/'website/static/subscription-demo.mp4'
    encoder=subprocess.Popen([str(FF),'-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s','1280x800','-r',str(FPS),'-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],stdin=subprocess.PIPE)
    pending=[];written=0;cue_times=[]
    for scene_index,scene in enumerate(scenes):
        cue_start=written/FPS
        frames_expected=round(scene['source_duration']/scene['speed']*FPS)
        decoder=subprocess.Popen([str(FF),'-loglevel','error','-ss',str(scene['start']),'-t',str(scene['source_duration']),'-i',str(scene['source']),'-vf',f"setpts=PTS/{scene['speed']},fps={FPS}",'-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stdout=subprocess.PIPE)
        frame_bytes=scene['size'][0]*scene['size'][1]*3
        buffer=[];index=0
        while True:
            raw=decoder.stdout.read(frame_bytes)
            if not raw:break
            if len(raw)!=frame_bytes:raise RuntimeError('Incomplete decoded frame')
            t=index/FPS
            frame=Image.frombytes('RGB',scene['size'],raw)
            if frame_editor:
                frame = frame_editor(frame, scene)
            if scene.get('pointer'):
                p=scene['pointer'];e=ease(t/p.get('move',.8))
                x=p['from'][0]+(p['to'][0]-p['from'][0])*e
                y=p['from'][1]+(p['to'][1]-p['from'][1])*e
                annotated=pointer(frame,x,y,t-p['click'] if t>=p['click'] else None)
                opacity=1-ease((t-p['fade'])/.35) if 'fade' in p else 1
                frame=Image.blend(frame,annotated,opacity)
            if scene.get('cursor'):
                e=ease((t-.1)/.8)
                x=925+(747-925)*e;y=440+(584-440)*e
                annotated=pointer(frame,x,y,t-1.0 if t>=1.0 else None)
                frame=Image.blend(frame,annotated,1-ease((t-1.5)/.35))
            z=ease((t-scene['zoom_start'])/(scene['zoom_end']-scene['zoom_start']))
            rect=[a+(b-a)*z for a,b in zip(scene['from'],scene['to'])]
            display=compose(frame,rect,scene['title'],scene['detail'],scene['step'],min(1,(written+len(buffer))/total_frames))
            buffer.append(display)
            index+=1
        decoder.stdout.close()
        if decoder.wait()!=0:raise RuntimeError('Decoding failed')
        if scene_index:
            for i in range(blend_frames):
                alpha=ease((i+1)/blend_frames)
                # A short directional transition preserves the real recorded screens.
                previous=pending[i];following=buffer[i]
                transition=BACKGROUND.copy();shift=round(alpha*transition_shift)
                transition.paste(previous,(-shift,0));layer=BACKGROUND.copy();layer.paste(following,(round((1-alpha)*transition_shift),0))
                transition=Image.blend(transition,layer,alpha)
                # Change the heading at the midpoint; crossfade only the footage.
                header=following if alpha>=.5 else previous
                transition.paste(header.crop((0,0,1280,158)),(0,0))
                transition.paste(header.crop((0,765,1280,800)),(0,765))
                encoder.stdin.write(transition.tobytes());written+=1
            buffer=buffer[blend_frames:]
        for frame in buffer[:-blend_frames]:
            encoder.stdin.write(frame.tobytes());written+=1
        pending=buffer[-blend_frames:]
        cue_times.append({'start':cue_start,'title':scene['title'],'detail':scene['detail']})
    for frame in pending:encoder.stdin.write(frame.tobytes());written+=1
    encoder.stdin.close()
    if encoder.wait()!=0:raise RuntimeError('Encoding failed')
    duration=written/FPS
    def stamp(t):
        ms=round(t*1000);return f'00:{ms//60000:02}:{ms//1000%60:02}.{ms%1000:03}'
    captions=['WEBVTT','']
    for i,cue in enumerate(cue_times):
        end=cue_times[i+1]['start'] if i+1<len(cue_times) else duration
        captions.extend([f"{stamp(cue['start'])} --> {stamp(end)}",cue['title']+'. '+cue['detail'],''])
    target.with_suffix('.vtt').write_text('\n'.join(captions),encoding='utf-8')
    subprocess.run([str(FF),'-y','-loglevel','error','-ss','5.1','-i',str(target),'-frames:v','1','-q:v','2',str(target.with_suffix('.jpg'))],check=True)
    (output/'edit.json').write_text(json.dumps({'duration':duration,'frames':written,'cues':cue_times,'scenes':[{**s,'source':str(s['source'])} for s in scenes]},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'duration':duration,'bytes':target.stat().st_size,'path':str(target)},ensure_ascii=False))


if __name__=='__main__':render()
