#-*- coding:utf-8 -*-
import os
import sys
import time
import codecs
import datetime
import diaspy
import redis
import json
import pickle
import requests
import random

from stream import md, csv_feed, to_csv, stream_to_graph
from diaspi import db_graph

DEBUG = os.environ.get('APP_DEBUG', "").lower() == "true"

# Flask
from flask import Flask
from flask import jsonify, make_response, render_template, redirect, request
app = Flask(__name__)
app.config['DEBUG'] = True

from flaskext.markdown import Markdown
Markdown(app, extensions=['markdown.extensions.extra'] )

REDIS_STORAGE = True
CALC_URL = "http://calc.padagraph.io/diaspfeed-export"
ENGINES_HOST = "http://localhost:5009"
STATIC_HOST = ""

ROBOTS = """
User-agent: *
Disallow: /
"""

from diasp import Diasp
conf = json.load(open('conf.json'))

__pod__ = conf['pod']
__username__ = conf['username']
__password__ = conf['password']
__host__ = conf['host']

diasp = Diasp( __pod__, __username__, __password__, host=__host__)

from pdglib.graphdb_ig import IGraphDB, engines
from cello.graphs import pedigree



if REDIS_STORAGE:
    import redis
    class RedisGraphs(object):
        def __init__(self, host='localhost', port=6379):
            # initialize the redis connection pool
            self.redis = redis.Redis(host=host, port=port)

        def __setitem__(self, gid, graph):
            # pickle and set in redis
            # todo ttl = 10
            self.redis.set(gid, pickle.dumps(graph))

        def get(self, gid):
            return self.__getitem__(gid)

        def __getitem__(self, gid):
            # get from redis and unpickle
            
            start = time.time()
            graph = pickle.loads(self.redis.get(gid))
            print( "loading %s from redis" % gid)
            
            if graph is None : 
                path = self.conf.get(gid, None)
                if path is None :
                    raise GraphError('no such graph %s' % gid) 
                else:
                    print( "opening graph %s@%s" %(gid, path))
                    graph = IgraphGraph.Read(path)

            end = time.time()

            print("redis time GET %s" % (end - start))
            if graph is not None:
                print( graph.summary())
                return graph

            raise GraphError('%s' % gid)

        def keys(self):
            return []

    graphdb = IGraphDB( graphs=RedisGraphs() )
        

graphdb.open_database()



from flask_login import LoginManager, current_user, login_user, login_required

login_manager = LoginManager()
login_manager.init_app(app)
   
from pdgapi import graphedit
 
edit_api = graphedit.graphedit_api("graphs", app, graphdb, login_manager, None )
app.register_blueprint(edit_api)

from pdglib.graphdb_ig import engines
from pdgapi.explor import layout_api
from diaspi import explore_api, clustering_api

api = explore_api(engines, graphdb)
api = layout_api(engines, api)
api = clustering_api(graphdb, engines, api)

app.register_blueprint(api)

from pdgapi import get_engines_routes

ME = diasp.me()

"""
# Routes
"""

 
@app.route("/")
@app.route('/readme', methods=['GET', 'POST'])
def home():
    md = codecs.open('readme.md', 'r', encoding='utf8').read()
    return render_template('home.html', readme=md , me=ME, pod=__pod__)

@app.route("/robots.txt") 
def robots():
    response = make_response(ROBOTS)
    response.headers["content-type"] = "text/plain"
    return response


"""
# Stream & Post
"""

def render_stream(stream, format=None, **kwargs):
    """
    format : None or 'json'
    """

    print(request.args)
    fullstream = diasp.get_stream()
    
    count = len(fullstream)

    size= 100;  size = min(int(request.args.get("size", size)),size)
    size = min(size, len(stream))
    start= 0;   start = max(int(request.args.get("start", start)),0)
    start = min(start, len(stream))
    

    d = dict(kwargs)
    d['stream_count'] = count
    d['people_count'] = len(set( [ t for e in fullstream for t in e['author'] ]))
    d['tags_count'] = len(set( [ t for e in fullstream for t in e['tags'] ]))
    d['start'] = start
    d['size'] = size
   
    d['prev'] = "?%s" % "&".join([ "start=%s" % max(0,start-size)  ])
    d['next'] = "?%s" % "&".join([ "start=%s" % (start+size)  ])

    stream = stream[start:start+size]

    for e in stream :
        e['md'] = md(e)

    if format=="json":
        return jsonify( stream )
        
    elif format=="csv":
        return render_csv_stream(stream, **d)
        
    return render_template('stream.html', pod=__pod__, me=ME, stream=stream, **d )



def render_csv_stream(stream, **kwargs):
    url = "http://calc.padagraph.io/_/diaspfeed"   
    headers, rows = csv_feed(stream)
    csv = to_csv(headers, rows)
    
    # POST csv
    print (" > POST   %s  %s" % (url, len(csv)) )
    r = requests.put(url, data=csv.encode('utf8'))
    url = url.replace('/_/', '/')

    md = """
# stream (%s)
> csv
[%s](%s)
    """ % (len(stream), url, url)

    return render_template('home.html',pod=__pod__, me=ME, readme=md, csv=csv, **kwargs )

@app.route("/fetch", methods=['GET', 'POST'])
def fetch():
    gid = 'diaspora'
    stream = diasp.get_stream(fetch=True)

    def f(e):
         return True   
         #d = int(e['created_at'].replace("-", "")[:8])
         #return d > 20180418
    stream = [ e for e in stream if f(e) ]
    graph = stream_to_graph(stream, "diaspora", host=ENGINES_HOST)
    graphdb.graphs[gid] = graph
    return redirect('/graph/%s' % gid)

@app.route("/stream", methods=['GET'])
def slashstream():
    stream = diasp.get_stream()
    return render_stream( stream )

@app.route("/stream.json", methods=['GET'])
def streamjson():
    stream = diasp.get_stream()
    return render_stream( stream, format="json" )

@app.route("/stream.csv", methods=['GET', 'POST'])
def streamcsv():
    stream = diasp.get_stream()
    return render_stream( stream, format="csv" )
    
@app.route("/stream/raw.json", methods=['GET'])
def rawjson():
    stream = diasp.get_raw_stream()
    return jsonify( stream )

@app.route("/post/<string:guid>", methods=['GET'])
def postguid(guid):
    stream = diasp.get_stream(post=guid)
    return render_stream( stream )

"""
# Tags
"""

@app.route("/tags", methods=['GET'])
def _tags(tag=None):
    stream = diasp.get_stream()
    tags = list(set( [ (t,1.) for e in stream for t in e['tags'] ] ))
    return render_stream([], tags=tags )

@app.route("/fetch/tag/<string:tag>", methods=['GET'])
def fetchtag(tag=None):
    stream = diasp.fetch_tag(tag)
    #return jsonify( stream ) 
    return redirect('/tag/%s' % tag)
    
@app.route("/tag/<string:tag>", methods=['GET'])
def tagstream(tag=None):
    stream = diasp.get_stream(tag=tag)
    return render_stream( stream, tag=tag )


"""
# People
### people data 
    {
        block: false,
        contact: false,
        diaspora_id: "utzer@social.yl.ms",
        guid: "409b3d8b46f6331b",
        id: 37695,
        is_own_profile: false,
        name: "utzer",
        profile: {
            avatar: {
            large: "https://social.yl.ms/photo/custom/300/7.jpg",
            medium: "https://social.yl.ms/photo/custom/100/7.jpg",
            small: "https://social.yl.ms/photo/custom/50/7.jpg"
            },
            id: 36043,
            searchable: true,
            tags: [
            "freifunk",
            "politik",
            "pirat",
            "piraten",
            "piratenpartei"
            ]
        },
        relationship: "not_sharing",
        show_profile_info: null
    }
"""


@app.route("/me", methods=['GET', 'POST'])
def me():
    return jsonify( ME )
    
@app.route("/contacts", methods=['GET', 'POST'])
def _contacts():
    return jsonify( contacts() )
    stream = []
    return render_stream(stream, users=[], count=len(stream) )

@app.route("/people", methods=['GET'])
def people(guid=None):
    people = { e['author']:{ 'name': e['author_name'], 'guid':e['author'], 'avatar':e['author_image'] } for e in diasp.get_stream() }
    people = list(people.values() )
    for p in people:
        stream = diasp.get_stream(people=p['guid'])
        p['stream_count'] = len( stream )
        p['tags']  = set( [ t for e in stream for t in e['tags']] )
    return render_stream( [], people=people )

@app.route("/fetch/people/<string:guid>", methods=['GET'])
def searchpeople(guid=None):
    fetch_people(guid)
    #return jsonify( stream ) 
    return redirect('/people/%s' % guid)
    
@app.route("/people/<string:guid>", methods=['GET'])
def peoplestream(guid=None):

    people = diasp.fetch_people(guid)
    stream = diasp.get_stream(people=guid)
    profile = people.data
   
    tags = set( [ t for e in stream for t in e['tags']  ] )
    posts = set( [ e['label'] for e in stream ] )
    profile['stream'] = {
        'posts': list(posts),
        'count': len(list(posts)),
        'tags': list(tags)
    }
    
    return render_stream(stream, user=profile, count=len(stream) )
    


"""
# Graph
"""
@app.route('/engines', methods=['GET'])
def _engines():
    host = ENGINES_HOST
    return jsonify({'routes': get_engines_routes(app, host)})

@app.route("/graph/", methods=['GET'])
@app.route("/graph/<string:gid>", methods=['GET'])
def graphsearch(gid=None):

    if gid is None :
        gid = hex(random.randint(10000,10000000000))[2:]

    query, graph = db_graph(graphdb, { 'graph':gid })
    
    routes = "%s/engines" % ENGINES_HOST
    sync = "%s/graphs/g/%s" % (ENGINES_HOST, gid)
    data = {}
    
    error = None
    
    #args
    args = request.args
     
    color = "#" + args.get("color", "249999" )    
    options = {
        #
        'wait' : 4,
        #template
        'zoom'  : args.get("zoom", 1200 ),
        'buttons': 0, # removes play/vote buttons
        'labels' : 1 if not args.get("no-labels", None ) else 0,  # removes graph name/attributes 
        # gviz
        'el': "#viz",
        'background_color' : color,
        'initial_size' : 16,
        'user_font_size' : 2,
        'user_vtx_size' : 1,
        'vtx_size' : args.get("vertex_size", 2 ),
        'show_text'  : 0 if args.get("no_text"  , None ) else 1,     # removes vertex text 
        'show_nodes' : 0 if args.get("no_nodes" , None ) else 1,   # removes vertex only 
        'show_edges' : 0 if args.get("no_edges" , None ) else 1,   # removes edges 
        'show_images': 0 if args.get("no_images", None ) else 1, # removes vertex images
        
        'auto_rotate': 0,
        'adaptive_zoom': True,
            
    }
    
    return render_stream([], graph=True ,
        static_host=STATIC_HOST, color=color,
        routes=routes, data=data, options=json.dumps(options), sync=sync )
     






from flask_runner import Runner
def main():
    ## run the app
    print ("running main")

    #build_app()

    runner = Runner(app)
    runner.run()

if __name__ == '__main__':
    sys.exit(main())
