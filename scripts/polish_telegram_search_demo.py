"""Edit the genuine Telegram search recording using the shared tutorial style."""
import json
from polish_subscription_demo import ROOT, render

out=ROOT/'diagnostics/hero-demo/telegram-search'
source=json.loads((out/'capture.json').read_text(encoding='utf-8'))['source']
scenes=[
 dict(start=4.6,source_duration=2.5,speed=.8,
      **{'from':(500,650,615,130),'to':(500,650,615,130)},
      title='Напишите название в боте',detail='Откройте КиноЖдуна → введите «Дюна» → отправьте',step=1,
      pointer={'from':(850,710),'to':(1080,759),'click':2.65,'move':2.5}),
 dict(start=32.2,source_duration=.4,speed=.13,
      **{'from':(505,385,490,255),'to':(505,465,490,255)},
      title='Выберите нужный фильм',detail='В результатах — «Дюна: Часть третья»',step=2,
      pointer={'from':(900,560),'to':(747,662),'click':2.5,'move':1.6}),
 dict(start=45.6,source_duration=1.65,speed=.65,
      **{'from':(505,330,490,255),'to':(505,420,490,255)},
      title='Нажмите «Ждать премьеру»',detail='Одна кнопка — и фильм в вашем списке',step=3,
      pointer={'from':(900,470),'to':(747,584),'click':2.05,'move':1.4}),
 dict(start=49,source_duration=3,speed=1,
      **{'from':(505,475,500,260),'to':(505,475,500,260)},
      title='Готово! КиноЖдун напомнит',detail='Бот подтвердил подписку на фильм',step=4),
]
for s in scenes:s.update(source=source,size=(1280,800),zoom_start=.1,zoom_end=1.8)
if __name__=='__main__':render(scenes,ROOT/'website/static/telegram-search-demo.mp4',out)
