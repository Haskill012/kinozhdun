import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_website import config
from website.content import Store
from website.catalog_views import project_page
from website.title_names import seo_names, source_seo_aliases


class TitleSEOTests(unittest.TestCase):
    def test_names_filter_provenance_duplicates_and_working_titles(self):
        detail={'alternative_titles':{'results':[
            {'title':'Русский вариант','iso_3166_1':'RU'},
            {'title':'Рабочее название','iso_3166_1':'RU','type':'Working Title'},
            {'title':'Other translation','iso_3166_1':'US'}]},
            'translations':{'translations':[{'iso_639_1':'ru','data':{'name':'Русский вариант'}}]}}
        self.assertEqual(source_seo_aliases(detail),['Русский вариант'])
        self.assertEqual(seo_names({'title':'Далёкий город','original_title':'Далекий город','aliases':['Любая строка']}),[])
        values=seo_names({'title':'Название','original_title':'Original','seo_aliases':['Русское имя','中文','Название','Русское имя','Ещё имя','Четвёртое имя']})
        self.assertEqual(values,['Original','Русское имя','Ещё имя'])

    def test_visible_names_metadata_and_schema_share_one_canonical_card(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'site.db')
            cfg=config(Path(directory)/'site.db');cfg['public']=True
            for media,id,title,original,alias,year in [('tv',225171,'Одна из многих','Pluribus','Плюрибус','2025'),
                                                      ('movie',627,'На игле','Trainspotting','Транспоттинг','1996')]:
                item=dict(key=f'{media}:{id}',id=id,media_type=media,title=title,original_title=original,
                          first_release=year+'-01-01',source_url=f'https://www.themoviedb.org/{media}/{id}',overview='Описание')
                html=project_page(store,cfg,item)
                suffix = 'дата выхода' if media == 'movie' else 'дата выхода серий'
                self.assertIn(f'<title>{title} ({original}, {year}) — {suffix} — КиноЖдун</title>',html)
                self.assertIn(f'<h1>{title}</h1><p class="project-alternate-names">',html)
                schema=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',html,re.S)[1])
                self.assertIn(original,schema['alternateName'])
                self.assertIn(alias,schema['alternateName'])
                self.assertEqual(schema['name'],title)
                self.assertEqual(schema['url'],cfg['base_url']+f'/title/{media}/{id}')
                self.assertIn(f'<link rel="canonical" href="{schema["url"]}">',html)
            store.db.close()

    def test_alias_html_is_escaped_and_plain_original_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'site.db');cfg=config(Path(directory)/'site.db')
            item=dict(key='movie:1',id=1,media_type='movie',title='Название',original_title='<script>alert(1)</script>',source_url='https://www.themoviedb.org/movie/1')
            html=project_page(store,cfg,item)
            self.assertNotIn('<script>alert(1)</script>',html)
            item['original_title']='Название'
            html=project_page(store,cfg,item)
            self.assertNotIn('project-alternate-names',html)
            self.assertNotIn('alternateName',html)
            store.db.close()
