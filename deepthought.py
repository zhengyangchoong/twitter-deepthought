#
# Main analysis module for compressed files. Imports crawler.py and aims to define functions 
# to parse and analyse the tweets in various ways, most probably with gensim
# 

from boto.s3.connection import Location, S3Connection
from boto.s3.key import Key
from gensim import corpora, models, similarities
import logging
import os
from nltk.corpus import stopwords
import gzip
from config import boto_access, boto_secret
import numpy as np
import json
import re
import cPickle as pickle #i don't care even if cPickle is much slower than alternatives like thrift or messagepack; i'm trying to get something done here
import brain.dicter, brain.cleaner
import base64
import logging

stop = stopwords.words('english')

def main():
	t = '31-03-2015_00'
	t_list = [
	'31-03-2015_02'
	]
	for r in t_list:		
		d = deepthought(r)
		d.load(t) #key from boto
		logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO, filename = '[LOG]-' + r)

		#
		# Setting force as True creates the thing again even though it might have already been generated and saved previously
		#
		d.clean()
		d.create_dict()
		#d.create_corpus(force = True)
		#d.create_tfidf(force = True)
		#d.create_lsi(force = True)
		#d.display_lsi(n = 100) #n being number of topics to display

def gen_date(parameters): 
# parameters as a dictionary
# 'months': (11,12)
# 'days': (12, 19)
# 'years': (2015, 2015) for consistency
# 'hours': (15,19)
# return a list
	a = datetime.datetime(parameters['years'][0], parameters['months'][0], parameters['days'][0], parameters['hours'][0])
	b = datetime.datetime(parameters['years'][1], parameters['months'][1], parameters['days'][1], parameters['hours'][1])
	c = b - a
	no_h = divmod(c.days * 86400 + c.seconds, 3600)[0]
	date_list = [b - datetime.timedelta(hours = x) for x in xrange(0, no_h)]
	date_list = map(lambda x: '{y}-{m}-{d}_{h}'.format(y = x.strftime('%Y'), m = x.strftime('%m'), d = x.strftime('%d'), h = x.strftime('%H')), date_list)
	return date_list


# this part assumes loading from boto
class deepthought(object):
	def __init__(self, key):
		self.conn = S3Connection(boto_access, boto_secret)
		self.bucket = self.conn.get_bucket('twitter-deepthought')
		self.key = key
		self.k = Key(self.bucket)
		self.k.key = self.key
		
		self.t_stop = ['rt', '#', 'http', '@'] #this is an arbitary stop list, and will change depending on analysis goals
		self.dirs = {
		'load':'thinking',
		'dump': os.path.join('thinking', 'braindump'),
		'dict': os.path.join('thinking', 'braindict'), #the last three are kind of redundant, will clear soon. were meant for pickling.
		'corp': os.path.join('thinking', 'braincorp'),
		'tfidf': os.path.join('thinking', 'braintfidf'),
		'lsi': os.path.join('thinking','brainlsi')
		}
		self.fp = {
		'lsi': os.path.join(self.dirs['lsi'], self.key + '.lsi'),
		'tfidf': os.path.join(self.dirs['tfidf'], self.key + '.tfidf_model'),
		'corp': os.path.join(self.dirs['corp'], self.key + '.mm')
		}
	def clean(self):
		broom = brain.cleaner.broom(self.f, self.key)
		broom.sweep()
	def ensure_dir(self,f): 
		if not os.path.exists(f):
			os.makedirs(f)
	def print_list(self):
		print "Key list: "
		for z in self.bucket.list():
			print z.name
	def load(self,savepath): 
		#load from boto here 
		self.ensure_dir(self.dirs['load'])
		if not os.path.exists(os.path.join('thinking', savepath + '.gz')):
			logging.info("Raw compressed file does not exist. Downloading.")
			print self.key
			self.k.get_contents_to_filename(os.path.join('thinking',savepath + '.gz'))
		self.f = gzip.open(os.path.join('thinking',savepath+'.gz'), 'rb')
		print self.f
		a = json.loads(self.f.readline())
		#print a['text']

	def create_dict(self):
		d = brain.dicter.librarian(self.key)
		d.gen()

	def create_corpus(self, force = False):
		logging.info("Attempting to create corpus...")
		self.ensure_dir(self.dirs['corp'])

		if os.path.exists(self.fp['corp']):
			if force == False:
				logging.info("Corpus exists already. Set force to True to create it again.")
			else:
				logging.info("Forced to create corpus.")
				self.corpus_creator()
		else:
			self.corpus_creator()

	def corpus_creator(self):
		self.f_dict = open(os.path.join(self.dirs['dict'], self.key),'rb+') #dictionary
		self.f_text = open(os.path.join(self.dirs['dump'], self.key),'rb+')
		self.dict = pickle.load(self.f_dict)
		corpora.MmCorpus.serialize(self.fp['corp'], [self.dict.doc2bow(line.split(' ')) for line in self.f_text])
	
		logging.info("Corpus created, and written into thinking/braincorpus/[KEY_NAME].mm in the Market Matrix format.")
		self.f_text.close()
		self.f_dict.close()
	def create_tfidf(self, force = False):
		logging.info("Attempting to create tf-idf model.")
		self.ensure_dir(self.dirs['tfidf'])
		if not os.path.exists(os.path.join(self.dirs['tfidf'], self.key + '.tfidf_model')):
			self.tfidf_creator()
		else:
			if force == True:
				logging.info("Forced to create Tf-idf model.")
				self.tfidf_creator()
			else:
				logging.info("Tf-idf model already created. Set force to True to create again.")
	def tfidf_creator(self):
		logging.info("Attempting to convert current corpus to the Tf-idf model...")
		self.f_corp = open(os.path.join(self.dirs['corp'], self.key + '.mm'), 'r')
		self.corpus = corpora.MmCorpus(self.f_corp)
		#print self.corpus

		self.tfidf = models.TfidfModel(corpus = self.corpus, dictionary = pickle.load(open(os.path.join(self.dirs['dict'], self.key))))
		self.corpus_tfidf = self.tfidf[self.corpus]
		print self.tfidf
		self.tfidf.save(self.fp['tfidf'])

		logging.info("Tf-idf model created, saved in tfidf_model format.")

	def create_lsi(self, force = False):
		#
		# Current approach: generate a seperate LSI / LSA for each time block, then compare over time
		# After initial development and for research purposes, consider collecting a few days worth of data, before creating a 'master' dictionary and 'corpus' to create a LSI/LSA model for topic-modelling 
		# In that case, ensure memory efficiency (i.e. not loading large chunks of data into memory), and possibly use a different organisational structure
		# Currently not very sure, but I'm guessing you'd add an option into the vector generator function to use the 'master' dict, and then add into the LSA structure
		#
		self.ensure_dir(self.dirs['lsi'])
		if os.path.exists(self.fp['lsi']):
			if force == True:
				logging.info("Forced to create LSI/LSA model again.")
				self.lsi_creator()
			else:
				logging.info("LSI/LSA model already created. Set force to True to create LSI model again.")
				pass
		else:
			self.lsi_creator()
	def lsi_creator(self, document_size = 1000):
		self.f_corp = open(os.path.join(self.dirs['corp'], self.key + '.mm'), 'r')
		self.corpus = corpora.MmCorpus(self.f_corp)

		self.tfidf = models.TfidfModel.load(self.fp['tfidf'])

		self.corpus_tfidf = self.tfidf[self.corpus]

		print self.tfidf
		self.dict = pickle.load(open(os.path.join(self.dirs['dict'], self.key)))
		self.lsi = models.LsiModel(self.corpus_tfidf, id2word = self.dict, num_topics = 200)
		self.corpus_lsi = self.lsi[self.corpus_tfidf] #double wrapper over the original corpus
		self.lsi.print_topics(5)
		self.lsi.save(self.fp['lsi'])
		logging.info("LSA model created.")
	def display_lsi(self, n = 10):

		self.lsi = models.LsiModel.load(self.fp['lsi'])

		self.lsi.print_debug(n)

if __name__ == '__main__':
	main()
