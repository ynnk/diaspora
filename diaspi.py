#!/usr/bin/env python
#-*- coding:utf-8 -*-

from flask import request, jsonify

import igraph
import datetime
import requests

from collections import Counter

from reliure.types import GenericType, Text, Numeric, Boolean
from reliure.web import ReliureAPI, EngineView, ComponentView, RemoteApi
from reliure.pipeline import Optionable, Composable
from reliure.engine import Engine

from cello.graphs import IN, OUT, ALL
from cello.graphs.prox import ProxSubgraph, pure_prox, sortcut

from cello.layout import export_layout
from cello.clustering import export_clustering

from pdgapi.explor import ComplexQuery, AdditiveNodes, NodeExpandQuery, layout_api, clustering_api

from botapad.utils import *

import stream


@Composable
def db_graph(graphdb, query, **kwargs):
    gid = query['graph']
    try : 
        graph = graphdb.get_graph(gid)
    except Exception as e:
        headers = stream.get_schema()
        graph = empty_graph(gid,  headers , **kwargs)
        graphdb.graphs[gid] = graph

    return query, graph


def vid(gid, v):
    if v['nodetype'] == ("_%s_article" % gid):
        e =  v['properties']['id']
    else :
        e =  v['nodetype'] + v['properties']['label']
    return e

@Composable
def index(gid, graph, **kwargs):
    idx = { vid(gid, v): v for v in graph.vs }
    return idx

  
@Composable
def query_api(gid, q, field, count=10, graph=None,**kwargs):
    url = istex.to_istex_url(q, field, count)
    g = stream.request_api_to_graph(gid, url, graph)
    g = prepare_graph(g)
    
    g['meta']['date'] = datetime.datetime.now().strftime("%Y-%m-%d %Hh%M")
    g['meta']['owner'] = None
    g['query'] = { 'q': q, 'field':field , 'url':url}
    
    return g
    

def _weights(weightings):
    def _w( graph, vertex):

        r = [(vertex, 1)] # loop
        
        for i in graph.incident(vertex, mode=ALL):
            e = graph.es[i]
            v = e.source if e.target == vertex else e.target

            w = (v, 1) # default

            if weightings:
                if "0" in weightings : 
                    w = (v, 0)
                if "1" in weightings : 
                    w = (v, 1)
            
                if "weight" in weightings:
                    w = (v, e['weight'])
                    
                if "author" in weightings:
                    if "_author" in e['edgetype'].lower() : 
                        w = (v, 5) 
                        
                if "tags" in weightings:
                    if "_tags" in e['edgetype'] :
                        w = (v, 5)
                        

            r.append( w )
                
        return r
    return _w

@Composable
def extract_articles(gid, graph, pz, weighting=None, length=3,  **kwargs):
    """
    : weight  :  scenario in ( '' , '' )
    """
    if weighting is None:
        weighting = ["1"]
        
    wneighbors = _weights(weighting)
    vs = pure_prox(graph, pz, length, wneighbors)
    return  vs

@Composable
def graph_articles(gid, graph, all_articles=True, cut=200, uuids=[], **kwargs):

    pz = [ (v.index,1.) for v in graph.vs if v['nodetype'] == ("_%s_article" % gid) ]

    if uuids and len(uuids):
        vids = [ v.index for v in graph.vs.select( uuid_in=uuids ) ]
        vs = extract_articles(gid, graph, dict(pz), **kwargs)
        vs = sortcut(vs,cut + len(vids) )
        vs = [ (v,s) for v,s in vs if v not in vids ][:cut]
        vs = vs + [ (v,1.) for v in vids ]
    else : 
        vs = extract_articles(gid, graph, dict(pz), **kwargs)
        vs = sortcut(vs,cut)

    if all_articles :
        vs = pz + vs
        
    return graph.subgraph( dict(vs).keys() )

    
def search_engine(graphdb):
    # setup
    engine = Engine("search")
    engine.search.setup(in_name="request", out_name="graph")

    ## Search
    def Search(query, results_count=10, **kwargs):
        query, graph = db_graph(graphdb, query)
        gid = query['graph']
        
        q = kwargs.pop("q", "*")
        field = kwargs.pop("field", None)
        
        g = query_api(gid, q, field, results_count)
        graph = merge(gid, graph, g, index=index, vid=vid)

        nodes = query['nodes']
        g = graph_articles(gid, graph, weighting=["1"], all_articles=True, cut=100, uuids=nodes, **kwargs )
        return g
        
    search = Optionable("Search")
    search._func = Search
    search.add_option("q", Text(default=u"clle erss"))
    search.add_option("field", Text(choices=[ u"*", u"author", u"tags" ], default=u"*"))
    search.add_option("results_count", Numeric( vtype=int, min=1, default=10, help="results count"))
    
    engine.search.set( search )
    return engine
 

def graph_engine(graphdb):
    # setup
    engine = Engine("graph")
    engine.graph.setup(in_name="request", out_name="graph")

    def _global(query, reset=False, all_articles=False, cut=100,  **kwargs):

        gid = query['graph']
        query, graph = db_graph(graphdb, query)
        nodes = [] if reset else query['nodes']
        g = graph_articles(gid, graph, all_articles=all_articles, cut=cut, uuids=nodes, **kwargs )
        return g
        
    comp = Optionable("Graph")
    comp._func = _global
    comp.add_option("reset", Boolean( default=False , help="reset or add"))
    comp.add_option("all_articles", Boolean( default=False , help="includes all articles"))
    comp.add_option("weighting", Text(choices=[  "0", "1", "weight" , "author", u"tags" ], multi=True, default=u"1", help="ponderation"))
    comp.add_option("length", Numeric( vtype=int, min=1, default=3))
    comp.add_option("cut", Numeric( vtype=int, min=2, default=100))

    def _reset_global(query, **kwargs):
        gid = query['graph']
        headers = istex.get_schema()
        graph = empty_graph(gid, headers, **kwargs)
        graphdb.graphs[gid] = graph
        g = graph_articles(gid, graph, all_articles=True, uuids=[], **kwargs )
        return g

    reset = Optionable('ResetGraph')
    reset._func = _reset_global
    reset.add_option("reset", Boolean( default=True , help="") , hidden=True)
    
    engine.graph.set( comp, reset )
    return engine

 
def import_calc_engine(graphdb):
    def _import_calc(query, calc_id=None, **kwargs):
        query, graph = db_graph(graphdb, query)
        if calc_id == None:
            return None
        url = "http://calc.padagraph.io/diasp-%s" % calc_id
        graph = istex.pad_to_graph(calc_id, url)
        graph['meta']['pedigree'] = pedigree.compute(graph)
        graph['properties']['description'] = url
        graphdb.graphs[calc_id] = graph
        return graph_articles(calc_id, graph, cut=100)
        
    comp = Optionable("import_calc")
    comp._func = _import_calc
    comp.add_option("calc_id", Text(default=None, help="identifiant du calc,le calc sera importé depuis l'adresse http://calc.padagraph.io/cillex-{calc-id}"))
    
    engine = Engine("import_calc")
    engine.import_calc.setup(in_name="request", out_name="graph")
    engine.import_calc.set( comp )

    return engine
 
def export_calc_engine(graphdb):
    def _export_calc(query, calc_id=None, **kwargs):

        if calc_id == None:
            return { 'message' : "No calc_id ",
                 'gid' : calc_id ,
                 'url': ""
                }
                
        query, graph = db_graph(graphdb, query)
        url = "http://calc.padagraph.io/_/diasp-%s" % calc_id
        print( "_export_calc", query, calc_id, url)

        headers, rows = stream.graph_to_calc(graph)
        print( "* PUT %s %s " % (url, len(rows)) ) 
        
        r = requests.put(url, data=istex.to_csv(headers, rows))
        url = "http://calc.padagraph.io/cillex-%s" % calc_id

        return { 'message' : "Calc exported ",
                 'gid' : calc_id ,
                 'url': url
                }
        
    export = Optionable("export_calc")
    export._func = _export_calc
    export.add_option("calc_id", Text(default=None, help="identifiant du calc, le calc sera sauvegardé vers l’adresse http://calc.padagraph.io/diasp-{calc-id}"))
    
    engine = Engine("export")
    engine.export.setup(in_name="request", out_name="url")
    engine.export.set( export )

    return engine



@Composable
def extract(graph, pz, cut=50, weighting=None, length=3, **kwargs):
    wneighbors = _weights(weighting)
    vs = pure_prox(graph, pz, length, wneighbors)
    vs = sortcut(vs,cut)
    return vs
    
def expand_prox_engine(graphdb):
    """
    prox with weights and filters on UNodes and UEdges types
    input:  {
                nodes : [ uuid, .. ],  //more complex p0 distribution
                weights: [float, ..], //list of weight
            }
    output: {
                graph : gid,
                scores : [ (uuid_node, score ), .. ]
            }
    """
    engine = Engine("scores")
    engine.scores.setup(in_name="request", out_name="scores")

    @Composable
    def Expand(query, **kwargs):
        
        query, graph = db_graph(graphdb, query)
        gid = query.get("graph")
        
        field = "*"
        expand = query['expand']
        nodes = query['nodes']
        vs = graph.vs.select( uuid_in=expand )
        
        if len(vs) == 0 :
            raise ValueError('No such node %s' % expand)

        v = vs[0]
        if ( v['nodetype'] == ("_%s_author" % gid) ):
            field = "auteurs"
            q = v['properties']['label']
        elif ( v['nodetype'] == ("_%s_tags" % gid) ):
            field = "tags"
            q = v['properties']['label']
        else: 
            q = v['properties']['label']

        # query expasnsion
        #g = query_api(gid, q, field)
        #graph = merge(gid, graph, g, index=index, vid=vid)

        pz = [ v.index ]
        vs = extract(graph, pz, **kwargs)
        vs = [ (graph.vs[i]['uuid'],v) for i,v in vs]
        #articles = [ (v['uuid'], 1.) for v in graph.vs if v['nodetype'] == ("_%s_article" % gid) ]
        return dict(  vs)
        

    scores = Optionable("scores")
    scores._func = Expand
    scores.name = "expand"
    engine.scores.set(scores)

    return engine


def explore_api(engines,graphdb ):
    #explor_api = explor.explore_api("xplor", graphdb, engines)
    api = ReliureAPI("xplor",expose_route=False)

    # import pad
    view = EngineView(import_calc_engine(graphdb))
    view.set_input_type(AdditiveNodes())
    view.add_output("graph", export_graph, id_attribute='uuid'  )
    api.register_view(view, url_prefix="import")    

    # istex search
    view = EngineView(search_engine(graphdb))
    view.set_input_type(ComplexQuery())
    view.add_output("request", ComplexQuery())
    view.add_output("graph", export_graph, id_attribute='uuid')

    api.register_view(view, url_prefix="search")

    # graph exploration, reset global
    view = EngineView(graph_engine(graphdb))
    view.set_input_type(ComplexQuery())
    view.add_output("request", ComplexQuery())
    view.add_output("graph", export_graph, id_attribute='uuid')

    api.register_view(view, url_prefix="graph")

    # prox expand returns [(node,score), ...]
    view = EngineView(expand_prox_engine(graphdb))
    view.set_input_type(NodeExpandQuery())
    view.add_output("scores", lambda x:x)

    api.register_view(view, url_prefix="expand_px")

    # additive search
    view = EngineView(engines.additive_nodes_engine(graphdb))
    view.set_input_type(AdditiveNodes())
    view.add_output("graph", export_graph, id_attribute='uuid'  )

    api.register_view(view, url_prefix="additive_nodes")    

    # export pad
    view = EngineView(export_calc_engine(graphdb))
    view.set_input_type(AdditiveNodes())
    view.add_output("url", lambda e: e )
    api.register_view(view, url_prefix="export")    

    return api


class Clusters(GenericType):
    def parse(self, data):
        gid = data.get('graph', None)
        clusters = data.get('clusters', None)

        if gid is None :
            raise ValueError('graph should not be null')
        if clusters is None :
            raise ValueError('clusters should not be null')

        return data
 
def clusters_labels_engine(graphdb):
    def _labels(query, weighting=None, count=2, **kwargs):
        query, graph = db_graph(graphdb, query)
        gid = query['graph']
        clusters = []
        for clust in query['clusters']:
            labels = []
            pz = graph.vs.select(uuid_in=clust)
            pz = [ v.index for v in pz if  v['nodetype'] == ("_%s_article" % gid ) ]
            if len(pz):
                vs = extract(graph, pz, cut=300, weighting=weighting, length=3)
                labels = [ { 'uuid' : graph.vs[i]['uuid'],
                             'label' : graph.vs[i]['properties']['label'],
                             'score' :  v }  for i,v in vs if graph.vs[i]['nodetype'] != ("_%s_article" % gid )][:count]
            clusters.append(labels)
        return clusters
        
    comp = Optionable("labels")
    comp._func = _labels
    comp.add_option("weighting", Text(choices=[  u"0", u"1", u"weight" , u"auteurs", "tags", ], multi=True, default=u"1", help="ponderation"))
    comp.add_option("count", Numeric( vtype=int, min=1, default=2))
    
    engine = Engine("labels")
    engine.labels.setup(in_name="request", out_name="labels")
    engine.labels.set( comp )

    return engine

# Clusters

def clustering_api(graphdb, engines, api=None, optionables=None, prefix="clustering"):
    
    def clustering_engine(optionables):
        """ Return a default engine over a lexical graph
        """
        # setup
        engine = Engine("gbuilder", "clustering")
        engine.gbuilder.setup(in_name="request", out_name="graph", hidden=True)
        engine.clustering.setup(in_name="graph", out_name="clusters")

        engine.gbuilder.set(engines.edge_subgraph) 
        engine.clustering.set(*optionables)

        return engine
        
    if api is None:
        api = ReliureAPI(name,expose_route = False)
        
    ## Clustering
    from cello.graphs.transform import EdgeAttr
    from cello.clustering.common import Infomap, Walktrap
    # weighted
    walktrap = Walktrap(weighted=True)
    walktrap.name = "Walktrap"
    infomap = Infomap(weighted=True) 
    infomap.name = "Infomap"

    DEFAULTS = [walktrap, infomap]

    if optionables == None : optionables = DEFAULTS

    from pdgapi.explor  import EdgeList
    view = EngineView(clustering_engine(optionables))
    view.set_input_type(EdgeList())
    view.add_output("clusters", export_clustering,  vertex_id_attr='uuid')
    api.register_view(view, url_prefix=prefix)

    # cluster labels
    view = EngineView(clusters_labels_engine(graphdb))
    view.set_input_type(Clusters())
    view.add_output("labels", lambda e: e )
    api.register_view(view, url_prefix="labels")
  

    return api