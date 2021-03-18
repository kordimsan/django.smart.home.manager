import requests
from django.conf import settings
from django.urls import reverse_lazy
from django.views.generic import FormView
from django.http import HttpResponse
from .form import ControllerForm
from .models import Setting


def get_or_update(controller_name, value):
    entry, created = Setting.objects.update_or_create(controller_name=controller_name)
    entry.value = value
    entry.save()

def get(controller_name, default):
    try:
        entry = Setting.objects.get(controller_name=controller_name)
        return entry.value
    except Setting.DoesNotExist:
        return default
    
class ControllerView(FormView):
    form_class = ControllerForm
    template_name = 'core/control.html'
    success_url = reverse_lazy('form')
    url = settings.SMART_HOME_API_URL
    headers = {'Authorization': f'Bearer {settings.SMART_HOME_ACCESS_TOKEN}'}

    def get_context_data(self, **kwargs):
        context = super(ControllerView, self).get_context_data()
        context['data'] = {}
        try:
            controller_data = requests.get(self.url,headers=self.headers).json()
            if controller_data.get('status') == 'ok':
                context['data'] = {x['name']:x['value'] for x in controller_data.get('data')}
        except:
            return HttpResponse(context, status=502)
        
        return context

    def get_initial(self):
        initial = super(ControllerView, self).get_initial()
        bedroom_target_temperature = get('bedroom_target_temperature', 21)
        hot_water_target_temperature = get('hot_water_target_temperature', 80)
        bedroom_light = get('bedroom_light', False)
        bathroom_light = get('bathroom_light', False)
        initial['bedroom_target_temperature'] = bedroom_target_temperature
        initial['hot_water_target_temperature'] = hot_water_target_temperature
        initial['bedroom_light'] = bedroom_light == 1
        initial['bathroom_light'] = bathroom_light == 1
        return initial

    def form_valid(self, form):
        get_or_update('bedroom_target_temperature', form.cleaned_data['bedroom_target_temperature'])
        get_or_update('hot_water_target_temperature', form.cleaned_data['hot_water_target_temperature'])
        get_or_update('bedroom_light', form.cleaned_data['bedroom_light'])
        get_or_update('bathroom_light', form.cleaned_data['bathroom_light'])
        payload = {'controllers': [
            {'name': 'bedroom_light', 'value': form.cleaned_data['bedroom_light']},
            {'name': 'bathroom_light', 'value': form.cleaned_data['bathroom_light']}
        ]}
        requests.post(self.url, headers=self.headers, json=payload)
        return super(ControllerView, self).form_valid(form)
