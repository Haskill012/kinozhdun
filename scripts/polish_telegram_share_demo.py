"""Two genuine sharing flows, using the common tutorial camera and typography."""
import json
from PIL import ImageDraw,ImageFont
from polish_subscription_demo import ROOT,render
out=ROOT/'diagnostics/hero-demo/telegram-share'
capture=json.loads((out/'capture.json').read_text(encoding='utf-8'))
source=capture['source'];events={e['label']:e['time'] for e in capture['events']}
def scene(label,duration,title,detail,step,rect,to=None,offset=-.15,speed=1):
    return dict(source=source,size=(1280,800),start=events[label]+offset,source_duration=duration,
                speed=speed,**{'from':rect,'to':to or rect},zoom_start=.1,zoom_end=1.3,
                title=title,detail=detail,step=step)
scenes=[
 scene('list-share',2.0,'Весь список: «Поделиться списком»','Откройте «Мой Кинождун» в боте',1,(505,480,490,255)),
 scene('list-recipient',.75,'Нажмите «Отправить друзьям»','Бот подготовит ваш список ожидания',2,(505,470,490,255),offset=-.4,speed=.42),
 scene('list-self',1.4,'Выберите чат для отправки','Пример чата с другом — Андрей Смирнов',3,(430,98,420,218),offset=-.4),
 scene('list-sent',.75,'Нажмите на готовый список','Telegram отправит карточку в выбранный чат',3,(515,630,585,115),offset=-.4,speed=.44),
 scene('list-sent',2.8,'Список отправлен','Получатель сможет открыть список и добавить проекты',4,(610,230,490,490),(610,450,490,255),offset=2.5),
 scene('item-share',.75,'Один фильм: «Поделиться с другом»','Откройте карточку нужного фильма или сериала',1,(505,398,405,330),(505,440,405,211),offset=-.4,speed=.38),
 scene('item-self',1.4,'Выберите чат','Карточку тоже можно отправить в любой чат',2,(430,98,420,218),offset=-.4),
 scene('item-sent',.75,'Выберите карточку с постером','Нажмите на подготовленный вариант сообщения',3,(515,570,590,155),offset=-.4,speed=.44),
 scene('item-sent',3,'Готово! Карточка отправлена','Друг сможет добавить фильм в свой список',4,(768,305,335,415),(768,545,335,174),offset=2.5),
]
for index in (2,6):
    scenes[index]['demo_contact'] = 'Андрей Смирнов'
    # Hold a genuine clean picker frame, then animate a cursor above the contact.
    scenes[index].update(start=scenes[index]['start']-.3,source_duration=.1,speed=.045,
        pointer={'from':(745,295),'to':(574,234),'move':1.15,'click':1.5,'fade':1.85})

# Keep a stable framing; rapid pans and aspect changes distracted from the action.
scenes[4].update(**{'to':(620,240,470,470)},zoom_end=2.7)
scenes[5].update(**{'to':scenes[5]['from']})
clean=json.loads((out/'clean-result/capture.json').read_text(encoding='utf-8'))
scenes[8].update(source=clean['source'],start=clean['start']+.4,source_duration=3.5,
    **{'from':(768,305,335,415),'to':(775,315,320,400)},zoom_end=3.3)

def demo_contact(frame, scene):
    """User-requested fictional recipient over the recorded picker, before cropping."""
    if not scene.get('demo_contact'):
        return frame
    # Stop the overlay as soon as the recorded picker closes.
    if min(frame.getpixel((440,300))) < 230:
        return frame
    d = ImageDraw.Draw(frame)
    regular = ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
    bold = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',16)
    small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf',14)
    d.rectangle((493,154,795,185),fill='white')
    d.text((496,160),'Андрей Смирнов',font=regular,fill='#111111')
    d.rectangle((509,221,809,270),fill='white')
    d.text((514,226),'Андрей Смирнов',font=bold,fill='#111111')
    d.text((514,248),'был недавно',font=small,fill='#707579')
    d.ellipse((457,221,503,267),fill='#8063b9')
    d.text((480,244),'АС',font=bold,anchor='mm',fill='white')
    d.rectangle((500,102,800,132),fill='#f4f4f5')
    d.text((503,107),'Отправить',font=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',20),fill='#111111')
    return frame

if __name__=='__main__':render(scenes,ROOT/'website/static/telegram-share-demo.mp4',out,frame_editor=demo_contact,blend_frames=12,transition_shift=0)
