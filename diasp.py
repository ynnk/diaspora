#-*- coding:utf-8 -*-


import requests
import json
import re

import requests
import codecs
import diaspy


from stream import csv_feed,to_csv, parse_stream, md, tags



class Diasp(object):
    
    def __init__(self, pod, username, password, host="http://localhost:5009"):
        self.__pod__      = pod
        self.__username__ = username
        self.__password__ = password
        self._connection = None
        self.__host__ = host

    def connection(self):
        self._connection = diaspy.connection.Connection( pod = self.__pod__, username = self.__username__, password = self.__password__)
        return self._connection
        
    def login(self):
        if self._connection is None:
            self.connection()
            self._connection.login()
        return self._connection

    def me(self):
        _me = diaspy.people.Me(self.login()).getInfo()
        return _me


    def fetch_stream(self, merge=True):
        c = self.login()
        stream = diaspy.streams.Generic(c)
        stream.more()
        stream.more()
       
        stream = json.loads(stream.json())

        if merge:
            stream = self.merge_stream(stream)

        return stream

    def merge_stream(self, stream):
        raw = self.get_raw_stream()
        
        ids = set([ e['guid'] for e in raw ])
        for e in stream:
            if e['guid'] not in ids :
                raw.append( e )
        
        self.write_stream(raw)
        return stream
        
    def write_stream(self, stream):
        with open( "stream.json", "w" ) as fw:
            fw.write(json.dumps(stream))

    def get_raw_stream(self, ):
        return self.get_stream(parse=False)

    def get_stream(self, fetch=False, parse=True, people=None, tag=None, post=None):
        stream = []

        if fetch : 
            self.fetch_stream()

        try:
            with open( "stream.json", "r" ) as fin:
                content = fin.read()
                if content and len(content):
                    stream = json.loads(content)
        except : pass

        stream.sort( key=lambda e : e['created_at'] )
        
        for e in stream :
            e['tags'] = tags( e, 'text')
        
        if post :
            stream = [ e for e in stream if post == e.get('guid', None) ]
        if people :
            stream = [ e for e in stream if people == e.get('author', {}).get('guid', None) ]
        if tag :
            stream = [ e for e in stream if tag.lower() in [ t.lower() for t in e.get('tags',[]) ] ]

        if parse : 
            stream = [ e for e in parse_stream(stream, host=self.__host__).values() ]
        
        return stream

    def fetch_tag(self, tag):
        c = login()
        stream = diaspy.streams.Tag(c, tag.lower())
        #stream.more()
        merge = json.loads(stream.json())
        self.merge_stream(merge)
        return stream

    def fetch_people(self, people):
        c = self.login()
        people = diaspy.people.User(c, guid=people )
        stream = json.loads(people.stream.json())
        self.merge_stream(stream)
        return people

    def contacts(self):
        c = self.login()
        vs = [ e.data for e in diaspy.people.Contacts(c).get() ]
        r = {
            'count': len(vs),
            'contacts': vs,
        }
        return r   
            
    def post(self, text):
        c = self.login()
        stream = diaspy.streams.Stream(c)
        p = stream.post(text)
        return p


