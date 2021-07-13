import os
from typing import Any, Dict, List, Optional, Tuple

from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import render
from django.http.response import HttpResponse, JsonResponse, Http404
from django.utils import translation
from django.urls import reverse
from pydantic import AnyHttpUrl

from access.config import CourseConfig
from access.course import Exercise, Chapter, Parent
from util import export


def index(request):
    '''
    Signals that the grader is ready and lists available courses.
    '''
    course_configs = CourseConfig.all()
    if request.is_ajax():
        return JsonResponse({
            "ready": True,
            "courses": [{"key": c.key, "name": c.data.name} for c in course_configs]
        })
    return render(request, 'access/ready.html', {
        "courses": course_configs,
    })


def course(request, course_key):
    '''
    Signals that the course is ready to be graded and lists available exercises.
    '''
    course_config = CourseConfig.get(course_key)
    if course_config is None:
        raise Http404()
    exercises = course_config.get_exercise_list()
    if request.is_ajax():
        return JsonResponse({
            "ready": True,
            "course_name": course_config.data.name,
            "exercises": _filter_fields(exercises, ["key", "title"]),
        })
    render_context = {
        'course': course_config.data,
        'exercises': exercises,
        'plus_config_url': request.build_absolute_uri(reverse(
            'aplus-json', args=[course_config.key])),
    }

    render_context["build_log_url"] = request.build_absolute_uri(reverse("build-log-json", args=(course_key, )))
    return render(request, 'access/course.html', render_context)


def exercise_model(request, course_key, exercise_key, parameter):
    '''
    Presents a model answer for an exercise.
    '''
    lang = request.GET.get('lang', None)
    (course, exercise, lang) = _get_course_exercise_lang(course_key, exercise_key, lang)

    path = None

    if 'model_files' in exercise:
        def find_name(paths, name):
            models = [(path,path.split('/')[-1]) for path in paths]
            for path,name in models:
                if name == parameter:
                    return path
            return None
        path = find_name(exercise['model_files'], parameter)

    if path:
        try:
            with open(CourseConfig.path_to(course.key, path)) as f:
                content = f.read()
        except FileNotFoundError as error:
            raise Http404("Model file missing") from error
        else:
            return HttpResponse(content, content_type='text/plain')

    raise Http404()


def exercise_template(request, course_key, exercise_key, parameter):
    '''
    Presents the exercise template.
    '''
    lang = request.GET.get('lang', None)
    (course, exercise, lang) = _get_course_exercise_lang(course_key, exercise_key, lang)

    path = None

    if 'template_files' in exercise:
        def find_name(paths, name):
            templates = [(path,path.split('/')[-1]) for path in paths]
            for path,name in templates:
                if name == parameter:
                    return path
            return None
        path = find_name(exercise['template_files'], parameter)

    if path:
        try:
            with open(CourseConfig.path_to(course.key, path)) as f:
                content = f.read()
        except FileNotFoundError as error:
            raise Http404("Template file missing") from error
        return HttpResponse(content, content_type='text/plain')

    raise Http404()


class JSONEncoder(DjangoJSONEncoder):
    def default(self, obj):
        if isinstance(obj, AnyHttpUrl):
            return str(obj)
        return super().default(obj)


def aplus_json(request, course_key):
    '''
    Delivers the configuration as JSON for A+.
    '''
    config = CourseConfig.get(course_key)
    if config is None:
        raise Http404()

    data = config.data.dict(exclude={"modules", "static_dir"}, exclude_none=True)

    def children_recursion(config: CourseConfig, parent: Parent) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for o in parent.children:
            of = o.dict(exclude={"children"}, exclude_none=True)
            if isinstance(o, Exercise) and o.config:
                exercise = config.exercise_config(o.key)
                data = export.exercise(request, config, exercise, of)
            elif isinstance(o, Chapter):
                data = export.chapter(request, config, of)
            else: # any other exercise type
                data = of
            data["children"] = children_recursion(config, o)
            result.append(data)
        return result

    modules = []
    for m in config.data.modules:
        mf = m.dict(exclude={"children"}, exclude_none=True)
        mf["children"] = children_recursion(config, m)
        modules.append(mf)
    data["modules"] = modules

    data["build_log_url"] = request.build_absolute_uri(reverse("build-log-json", args=(course_key, )))
    return JsonResponse(data, encoder=JSONEncoder)


def _get_course_exercise_lang(
        course_key: str,
        exercise_key: str,
        lang_code: Optional[str]
        ) -> Tuple[CourseConfig, Dict[str, Any], str]:
    # Keep only "en" from "en-gb" if the long language format is used.
    if lang_code:
        lang_code = lang_code[:2]
    config = CourseConfig.get(course_key)
    if config is None:
        raise Http404()
    exercise = config.exercise_data(exercise_key, lang=lang_code)
    if exercise is None:
        raise Http404()
    if not lang_code:
        lang_code = config.lang
    translation.activate(lang_code)
    return (config, exercise, lang_code)


def _filter_fields(dict_list, pick_fields):
    '''
    Filters picked fields from a list of dictionaries.

    @type dict_list: C{list}
    @param dict_list: a list of dictionaries
    @type pick_fields: C{list}
    @param pick_fields: a list of field names
    @rtype: C{list}
    @return: a list of filtered dictionaries
    '''
    result = []
    for entry in dict_list:
        new_entry = {}
        for name in pick_fields:
            new_entry[name] = entry[name]
        result.append(new_entry)
    return result
