#-*- coding:utf-8 -*-

from __future__ import unicode_literals

import csv
import json
import requests
import datetime
import urllib
import collections
import re
from six import StringIO

from botapi import BotaIgraph
from botapad import Botapad
from botapad.utils import empty_graph

# parse response attributes
def _key(e, k, **kw) :
    return e.get(k)

def _list(e, k, **kw) :
    return  ";".join(e.get(k, []))

def _auteurs(e,k, **kw):
    name = e['author']['name']
    return name
    
def _auteurs_guid(e,k, **kw):
    name = e['author']['guid']
    return name

def _auteurs_img(e,k, **kw):
    name = e['author']['avatar']['small']
    return name

def _url(e,k, **kw):
    url = "%s/post/%s" % (kw.get('host'),_key(e,'guid'))
    return url


def tags( e, k, **kw ):
    text = e[k]
    tags = re.findall('#(\w+)', text)
    return tags


def _f(x):
    groups = list(x.groups())
    if groups[0] in ( None, '') :  groups[0] = '  \n'
    if groups[1] in ( None, '') :  groups[1] = groups[2]
    return "%s[%s](%s)  \n" % tuple(groups)

RETAG = r"#([\-\w]+)"
REMD= r"(?:([\!])?(?:\[([\w\s\-'…«»\*,\!_\.\(\)]+)?\])?\(?(https?\:\/\/[;~,%\*:=\?&\-\.\/\w]+)\)?)"

def md(e):
    text = e['text']
    
    text = re.sub( REMD , _f,  text, flags=re.UNICODE)

    text = re.sub( RETAG, lambda x: "[%s](/tag/%s)" % (x.group(0),x.group(0)[1:]) , text)

    return text
    
def flatten(l):
    for el in l:
        if isinstance(el, collections.Iterable) and not isinstance(el, basestring):
            for sub in flatten(el):
                yield sub
        else:
            yield el

SHAPES = {
    "article" : "square",
    "auteurs" : "circle",
    "tags" : "triangle-top",
 }

        
COLS = [
    #( api name, func, csv syntax, csv name )
    ('guid', _key  , "#", "guid"),
    ('id', _key  , "", "id"),
    ('created_at', _key  , "", "created_at"),
    ('url', _url  , "", "url"),
    
    ('author', _auteurs  , "+", "author_name"),
    ('author', _auteurs_guid  , "+%", "author"),
    ('author', _auteurs_img  , "+", "author_image"),
    ('title', _key  , "", "label"),
    ('text', _key  , "", "text"),
    ('text', tags  , "%+", "tags"),
    
    #('photos', _list  , "+", "photos"),
    #('mentioned_people', _list  , "+", "mentioned_people"),
    ('nsfw', _key  , "", "nsfw"),
    
    ('shape', lambda e,k, **kw: "square", "", "shape"),
 ]

 

_COLORED = u"""
_ article_author, color[#555], width[3], line[plain]
_ article_tags,	color[#EEE], width[1], line[plain]

@tags: #label, shape[triangle-top], color[#EEE]	
@author: #guid, label, image, stream, shape[circle], size[1.3]	
"""

def get_schema():           
    # basic
    SCHEMA = [ [ "@%s: #label" % k , "shape[%s]" %v ]  for k,v in SHAPES.items() if k != "article"]
    # colored
    SCHEMA = [ e.split(',') for e in _COLORED.split("\n") if len(e) ]

    headers = [ "%s%s" % (e[2],e[3]) for e in COLS ]
    headers[0] = "@article: %s" % headers[0]
    headers = SCHEMA + [headers]

    return headers


def parse_stream(stream, **kwargs):
    
    s = list( { n:f(e,k, **kwargs) for k, f, m, n in COLS }  for e in stream )
    return { e['guid']:e for e in s }

    
def csv_feed(feed):
    comments = "! %s\n" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    headers = [[comments]] + get_schema()
    rows = [ [  hit.get(e[3]) for e in COLS ] for hit in feed ]
    return headers, rows


def to_csv(headers, rows):
    out = StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL)
    writer.writerows( headers )

    for row in rows :
        writer.writerow(row )

    return out.getvalue()


def stream_to_graph(stream, gid, graph=None, host=""):

    headers = [ e.split(',') for e in _COLORED.split("\n") if len(e) ]

    people = { e['author']: [e['author'], e['author_name'],  e['author_image'], "%s/people/%s" %(host, e['author'] )]  for e in stream }
    people =  headers + list(people.values() )

    print(people)
    
    
    headers = [ "%s%s" % (e[2],e[3]) for e in COLS ]
    headers[0] = "@article: %s" % headers[0]
    headers =  [headers]
    
    f = lambda x : ",".join(x)  if  type(x)  == list else x 
    rows = [ [  f(post[e[3]]) for e in COLS ] for post in stream ]
    print( "HEADERS \n", headers )

    rows = people + headers + rows   
    bot = BotaIgraph(directed=True)
    botapad = Botapad(bot , gid, "", delete=False, verbose=True, debug=False)
    botapad.parse_csvrows( headers + rows, separator='auto', debug=False)

    g = bot.get_igraph(weight_prop="weight")
    
    return g


def request_api_to_graph(gid, url, graph=None):
    
    headers = None if graph is None else graph_to_calc_headers(graph)
    headers, rows = request_api(url)
    #print "HEADERS \n", headers
    #print "ROWS \n", rows
    bot = BotaIgraph(directed=True)
    botapad = Botapad(bot , gid, "", delete=False, verbose=True, debug=False)
    botapad.parse_csvrows( headers + rows, separator='auto', debug=False)
    graph = bot.get_igraph(weight_prop="weight")
    
    return graph



def graph_to_calc_headers(graph):

    headers = []        
    comments = [
            [ "! %s  V:%s E:%s" % ( graph['properties']['name'], graph.vcount(), graph.ecount())  ],
            [ ], ] + [  ["! %s" % json.dumps(graph['queries'])  ] ]
            
    nodetypes = [ e['name'] for e in graph['nodetypes']]
    for k in nodetypes:
        if k != "article":
            headers.append(["@%s: #label" % k, "shape[%s]" % SHAPES.get(k, "")])

    headers = comments + headers + [[],[]]
    keys = []
    for i,col in enumerate(COLS):
        col = col[3]
        key = ""
        if i == 0 :
            key = "@article:"
        isindex = col == "id"
        isproj = col in nodetypes
        key = "%s%s%s%s%s" % (key, "#" if isindex else "", "%+" if isproj else "", "", col)
        keys.append(key)

    headers = headers + [keys] 
    return headers
    
def graph_to_calc(graph):
    
    headers = graph_to_calc_headers(graph)
    rows = []

   
    nodetypes = [ e['name'] for e in graph['nodetypes']]
    nodetypes_idx = { e['uuid']:e for e in graph['nodetypes'] }

    articles = [ v for v in graph.vs if nodetypes_idx[v['nodetype']]['name'] == "article" ]

    for v in articles:
        row = []
        for i, col in enumerate(COLS):
            col = col[3]
            isindex = col == "id"
            isproj = col in nodetypes
            
            #print col, isindex, isproj, nodetypes_idx[v['nodetype']]['name'], v["properties"]['label']

            if not isproj:
                row.append(v['properties'][col])
            else:
                cell = []
                for e in v.neighbors():
                    n = nodetypes_idx[e['nodetype']]['name']
                    if n == col :
                        cell.append(e['properties']['label'])
                row.append(';'.join(cell))
        rows.append(row)
    return headers, rows



  
    

