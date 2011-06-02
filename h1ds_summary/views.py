
from django.shortcuts import render_to_response
from django.core.cache import cache
from django.db.models import Max
from django.views.decorators.cache import never_cache
from django.utils import simplejson
from django.http import HttpResponse, HttpResponseRedirect
from django.template import RequestContext
from django import forms
from django.db import connection
from django.core.urlresolvers import reverse

from h1ds_summary.models import Shot, SummaryAttribute

DEFAULT_SHOT_REGEX = "last10"

def do_html_data(data, attr_list):
    output_data = []
    for row in data:
        row_data = [row[0]]
        for attr_i,attr_data in enumerate(row[1:]):
            attr_value = attr_data
            if attr_list[attr_i].display_format:
                try:
                    attr_value = attr_list[attr_i].display_format %(attr_data)
                except:
                    pass
            row_data.append({'val':attr_value, 'norm':int(100.0*attr_list[attr_i].normalise(attr_data)), 'col':attr_list[attr_i].colourise(attr_data), 'show_barplot':attr_list[attr_i].show_barplot()})
        output_data.append(row_data)
    return output_data


def get_vis_attr_data(path, attr_list):
    if len(attr_list) == 1:
        return [{'att':attr_list[0], 'newpath':None}]
    output = []
    spl_path = path.split("/")
    if len(spl_path) == 3: # path=/summary/ -> add default shots and another trailing /
        spl_path[2] = DEFAULT_SHOT_REGEX
        spl_path.append("")
    if len(spl_path) == 4:
        spl_path[3] = 'all'
        spl_path.append("")
    for att in attr_list:
        newpath = '+'.join([i.slug for i in attr_list if not i==att])
        spl_path[3] = newpath
        output.append({'att':att, 'newpath':'/'.join(spl_path)})
    return output


def get_hidden_attr_data(path, attr_list, n_cols=2):
    all_attrs = SummaryAttribute.objects.all()
    output = []
    spl_path=path.split('/')
    if len(spl_path) == 3: # path=/summary/ -> add default shots and another trailing /
        spl_path[2] = DEFAULT_SHOT_REGEX
        spl_path.append("")
    tmp_path = '+'.join([i.slug for i in attr_list])
    for a in all_attrs:
        if not a in attr_list:
            spl_path[3] = "+".join([tmp_path, a.slug])
            output.append({'att':a, 'newpath':'/'.join(spl_path)})
    sorted_list = sorted(output, key=lambda k: k['att'].slug.lower())
    sorted_output = []
    n_rows = float(len(sorted_list))/n_cols
    n_delta =int( n_rows)
    if n_rows%1 != 0:
        n_rows +=1
    n_rows = int(n_rows)
    for j in range(n_rows):
        sorted_output.extend(sorted_list[j::n_rows])
    return sorted_output

def overview(request, shot_regex=DEFAULT_SHOT_REGEX, data_regex="default", filter_regex=None, format="html", n_cols_sidebar = 2):
    if SummaryAttribute.objects.count() == 0:
        return render_to_response('h1ds_summary/no_attributes.html', {}, context_instance=RequestContext(request))
    if Shot.objects.count() == 0:
        return render_to_response('h1ds_summary/no_shots.html', {}, context_instance=RequestContext(request))
    [data,attr_list] = Shot.objects.summarydata(shot_regex, attr_query=data_regex, filter_query=filter_regex)
    html_data = do_html_data(data, attr_list)
    visible_attr_data = get_vis_attr_data(request.path, attr_list)
    hidden_attr_data = get_hidden_attr_data(request.path, attr_list, n_cols=n_cols_sidebar)
    if 'last' in shot_regex:
        update=True
    else:
        update=False
    latest_shot = Shot.objects.aggregate(Max('shot'))['shot__max']
    return render_to_response('summary/overview.html', {'data':html_data, 'attrs':visible_attr_data, 'hidden':hidden_attr_data, 'update':update, 'latest_shot':latest_shot}, context_instance=RequestContext(request))

@never_cache
def latest_shot(request, format="html"):
    latest_shot = cache.get("latest_summary_shot", 0)
    view = request.GET.get('view', 'html')
    if not latest_shot > 0:
        latest_shot = Shot.objects.aggregate(Max('shot'))['shot__max']
        #cache.set("latest_summary_shot", latest_shot, 60*60*6)
        cache.set("latest_summary_shot", latest_shot, 3)
    if view == 'xml':
        xmlstr = """<?xml version="1.0" encoding="UTF-8" ?>
        <shot>
        <number>%d</number>
        <comment>Latest shot in summary database</comment>
        </shot>""" %latest_shot
        return HttpResponse(xmlstr, mimetype='text/xml; charset=utf-8')
    else:
        return render_to_response('summary/latest_shot.html', {'shot':latest_shot}, context_instance=RequestContext(request))


@never_cache
def ajax_latest_shot(request):
    latest_shot = cache.get("latest_summary_shot", 0)
    if not latest_shot > 0:
        latest_shot = Shot.objects.aggregate(Max('shot'))['shot__max']
        #cache.set("latest_summary_shot", latest_shot, 60*60*6)
        cache.set("latest_summary_shot", latest_shot, 3)

    d = {'shot':latest_shot}
    return HttpResponse(simplejson.dumps(d))

class RawSqlForm(forms.Form):
    select = forms.CharField(widget=forms.Textarea)
    where = forms.CharField(widget=forms.Textarea)


def raw_sql(request, tablename="summary"):
    """Provide a form for users to request a raw SQL query and display the results."""
    if request.method == 'POST':
        form = RawSqlForm(request.POST)
        if form.is_valid():
            cursor=connection.cursor()
            cursor.execute("SELECT %s FROM %s WHERE %s" %(form.cleaned_data['select'], tablename, form.cleaned_data['where']))
            data = cursor.fetchall()
            return render_to_response('summary/raw_sql.html', {
                    'form': form, 'tablename':tablename, 'data':data, 'labels':form.cleaned_data['select'].split(',')}, context_instance=RequestContext(request))
    elif request.method == 'GET':
        select_str = request.GET.get('select', '')
        where_str = request.GET.get('where', '')
        if not '' in [select_str, where_str]:
            cursor=connection.cursor()
            cursor.execute("SELECT %s FROM %s WHERE %s" %(select_str, tablename, where_str))
            data = cursor.fetchall()
            form = RawSqlForm({'select':select_str, 'where':where_str})
            view = request.GET.get('view', 'html')
            if view.lower() == 'raw':
                return HttpResponse(data, mimetype='text/plain')

            else:
                return render_to_response('summary/raw_sql.html', {
                        'form': form, 'tablename':tablename, 'data':data, 'labels':select_str.split(',')}, context_instance=RequestContext(request))
            
            
    form = RawSqlForm()

    return render_to_response('summary/raw_sql.html', {
            'form': form, 'tablename':tablename}, context_instance=RequestContext(request))

    
# NEW CODE:::::

from urlparse import urlparse
import json
from django.core.urlresolvers import resolve
from django.http import QueryDict

# Map mdsplus datatypes to MySQL datatypes
# TODO: This should not depend on the database type, check that we don't
# restrict ourselves to MySQL over postgres, etc
# The single-character SQL type codes are mapped to the actual types in h1ds_summary.models.sql_type_codes
mds_sql_map = {
    'DTYPE_FLOAT':'N',
    }



from h1ds_summary.forms import SummaryAttributeForm

def add_summary_attribute(request):
    # Take a HTTP post with  a filled SummaryAttributeForm, and create a
    # SummaryAttribute instance.
    # TODO: provide forms with return url, especially when 
    if request.method == 'POST':
        summary_attribute_form = SummaryAttributeForm(request.POST)
        if summary_attribute_form.is_valid():
            summary_attribute_form.save()
            return_url = request.POST.get('return_url', reverse("h1ds-summary-homepage"))
            return HttpResponseRedirect(return_url)            
        else:
            return render_to_response('h1ds_summary/form.html',
                                      {'form': summary_attribute_form,
                                       'submit_url':reverse('add-summary-attribute')},
                                      context_instance=RequestContext(request))
            
    else:
        return HttpResponseRedirect(reverse("h1ds-summary-homepage"))
    

def get_summary_attribute_form_from_url(request):
    """Take a H1DS mdsplus web URL and return a SummaryAttributeForm.

    The request should contain a 'url' POST query with a URL pointing to
    a mdsplus data node (can include  filters).  The URL must point to a
    path in the same django instance.

    We first call the URL and check what datatype is returned so we know
    which SQL datatype to use, then we pre-fill a form to be complete by
    the user.
    """
    # Get the requested URL from the POST data
    attr_url = request.POST['url']

    # Split URL into [scheme, netloc, path, params, query, fragments]
    parsed_url = urlparse(attr_url)

    # Get the django view function corresponding to the URL path
    view, args, kwargs = resolve(urlparse(attr_url)[2])

    # Create a  new query  dict from the  queries in the  requested URL,
    # i.e. data filters, etc, and add ?view=json
    new_query = QueryDict(parsed_url[4]).copy()
    new_query.update({'view':'json'})

    # Insert our new query dict into the request sent to this view...
    request.GET = new_query    

    # ...and use this request to call the view function and get the data
    # for the requested URL.
    kwargs['request'] = request
    url_response = view(*args, **kwargs)

    # url_response content is a string, let's convert it to a dictionary
    # using the json parser.
    json_data = json.loads(url_response.content)    

    # Determine from  the MDSplus datatype which SQL  datatype should be
    # used
    mds_dtype = json_data['mds_dtype']
    sql_dtype = mds_sql_map[mds_dtype]

    # Now we generalise the URL  for any shot, replacing the shot number
    # with %(shot)d
    general_url = attr_url.replace(kwargs['shot'], "%(shot)d")

    # Create a SummaryAttributeForm with URL and data type entries pre-filled
    summary_attribute_form = SummaryAttributeForm(initial={'source_url':general_url, 'data_type':sql_dtype})

    # If the request is from AJAX, return form in JSON format
    # TODO: provide ajax / sidebar attribute adding.
    # if request.is_ajax():

    # Otherwise, forward user to form entry page
    return render_to_response('h1ds_summary/form.html',
                              {'form': summary_attribute_form, 'submit_url':reverse('add-summary-attribute')},
                              context_instance=RequestContext(request))
    
