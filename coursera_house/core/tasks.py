from __future__ import absolute_import, unicode_literals

import json
from types import SimpleNamespace

import requests
from celery import task
from django.conf import settings
from django.core.mail import EmailMessage
from django.http import HttpResponse
from .models import Setting

url = settings.SMART_HOME_API_URL
headers = {'Authorization': f'Bearer {settings.SMART_HOME_ACCESS_TOKEN}'}

def append_if_not_in(lst,itm):
    if itm not in lst:
         lst.append(itm)
    return lst

@task()
def smart_home_manager():
    try:
        controller_data = requests.get(url, headers=headers).json()
        if controller_data['status'] != 'ok':
            return HttpResponse('Some problems with API', status=502)
    except:
        return HttpResponse('Some problems with API', status=502)
    
    json_data = {x['name']:x['value'] for x in controller_data.get('data')}
    controllers = json.loads(json.dumps(json_data), object_hook=lambda d: SimpleNamespace(**d))
    
    payload = {'controllers': []}
    
    # Если есть протечка воды (leak_detector=true), закрыть холодную (cold_water=false) 
    # и горячую (hot_water=false) воду и отослать письмо в момент обнаружения.
    if controllers.leak_detector:
        if controllers.cold_water:
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'cold_water', 'value': False})
            controllers.cold_water = False
        if controllers.hot_water:
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'hot_water', 'value': False})
            controllers.hot_water = False

        email = EmailMessage(
            'leak detector',
            'text',
            settings.EMAIL_HOST,
            [settings.EMAIL_RECEPIENT],
        )
        email.send(fail_silently=False)
    
    # Если холодная вода (cold_water) закрыта, немедленно выключить бойлер (boiler) и стиральную машину (washing_machine) 
    # и ни при каких условиях не включать их, пока холодная вода не будет снова открыта.
    if not controllers.cold_water:
        if controllers.boiler:
            controllers.boiler = False
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'boiler', 'value': False})
        if controllers.washing_machine in ('on', 'broken'):
            controllers.washing_machine = 'off'
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'washing_machine', 'value': 'off'})
    
    # Если обнаружен дым (smoke_detector), немедленно выключить следующие приборы 
    # [air_conditioner, bedroom_light, bathroom_light, boiler, washing_machine], 
    # и ни при каких условиях не включать их, пока дым не исчезнет
    if controllers.smoke_detector:
        if controllers.air_conditioner:
            controllers.air_conditioner = False
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'air_conditioner', 'value': False})
        if controllers.bedroom_light:
            controllers.bedroom_light = False
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'bedroom_light', 'value': False})
        if controllers.bathroom_light:
            controllers.bathroom_light = False
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'bathroom_light', 'value': False})
        if controllers.boiler:
            controllers.boiler = False
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'boiler', 'value': False})
        if controllers.washing_machine in ('on', 'broken'):
            controllers.washing_machine = 'off'
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'washing_machine', 'value': 'off'})

    # Если горячая вода имеет температуру (boiler_temperature) меньше чем hot_water_target_temperature - 10%, нужно включить бойлер (boiler), 
    # и ждать пока она не достигнет температуры hot_water_target_temperature + 10%, после чего в целях экономии энергии бойлер нужно отключить
    hot_water_target_temperature = Setting.objects.get(controller_name='hot_water_target_temperature').value
    if (controllers.boiler_temperature or 0) < hot_water_target_temperature * 0.9 and not controllers.boiler and not controllers.smoke_detector and controllers.cold_water:
        controllers.boiler = True
        payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'boiler', 'value': True})
    
    if (controllers.boiler_temperature or 0) > hot_water_target_temperature * 1.1 and controllers.boiler:
        controllers.boiler = False
        payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'boiler', 'value': False})
    
    # Если шторы частично открыты (curtains == “slightly_open”), то они находятся на ручном управлении 
    # - это значит их состояние нельзя изменять автоматически ни при каких условиях
    # Если на улице (outdoor_light) темнее 50, открыть шторы (curtains), но только если не горит лампа в спальне (bedroom_light). 
    # Если на улице (outdoor_light) светлее 50, или горит свет в спальне (bedroom_light), закрыть шторы. Кроме случаев когда они на ручном управлении
    if controllers.curtains != "slightly_open":
        if controllers.outdoor_light < 50 and not controllers.bedroom_light and controllers.curtains == 'close':
            controllers.curtains = 'open'
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'curtains', 'value': 'open'})
    
        if (controllers.outdoor_light > 50 or controllers.bedroom_light) and controllers.curtains == 'open':
            controllers.curtains = 'close'
            payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'curtains', 'value': 'close'})

    # Если температура в спальне (bedroom_temperature) поднялась выше bedroom_target_temperature + 10% - включить кондиционер (air_conditioner), 
    # и ждать пока температура не опустится ниже bedroom_target_temperature - 10%, после чего кондиционер отключить
    bedroom_target_temperature = Setting.objects.get(controller_name='bedroom_target_temperature').value
    if controllers.bedroom_temperature < bedroom_target_temperature * 0.9 and controllers.air_conditioner:
        controllers.boiair_conditionerler = False
        payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'air_conditioner', 'value': False})
    
    if controllers.bedroom_temperature > bedroom_target_temperature * 1.1 and not controllers.air_conditioner and not controllers.smoke_detector:
        controllers.air_conditioner = True
        payload['controllers'] = append_if_not_in(payload['controllers'],{'name': 'air_conditioner', 'value': True})
    

    if payload['controllers']:
        try:
            r = requests.post(url, headers=headers, json=payload)
            if r.json()['status'] != 'ok':
                return HttpResponse('Some problems with API', status=502)
        except:
            return HttpResponse('Some problems with API', status=502)

        