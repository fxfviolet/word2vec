from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import math
import os
import random
from tempfile import gettempdir
import zipfile

import numpy as np
from six.moves import urllib
from six.moves import xrange   
import tensorflow as tf

from matplotlib import rcParams                  
from matplotlib.font_manager import FontProperties
import matplotlib.pyplot as plt

# matplotlib输出中文的时候会出现乱码，对matplotlib进行设置，使之可以输出中文
myfont =  FontProperties(fname='wqy-microhei.ttc',size=20)
rcParams['axes.unicode_minus']=False                             # 解决负号‘-‘显示为方块的问题


# Step 1: 读取训练数据
filename = './text.txt'

# 将数据转成词语列表
def read_data(filename):
  with open(filename, encoding="utf-8") as f:
    data = f.read()
  data = list(data)
  return data

vocabulary = read_data(filename)
print('Data size', len(vocabulary))


# Step 2: 建立词语字典
vocabulary_size = 5000                                                # 取出现次数最多的前5000个单字符
def build_dataset(words, n_words):
  count = [['UNK', -1]]                                                # 生成列表count
  count.extend(collections.Counter(words).most_common(n_words - 1))
  dictionary = dict()                                                  # 生成字典dictionary                    
  for word, _ in count:
    dictionary[word] = len(dictionary)
  data = list()
  unk_count = 0
  for word in words:
    index = dictionary.get(word, 0)
    if index == 0:   
      unk_count += 1
    data.append(index)
  count[0][1] = unk_count
  reversed_dictionary = dict(zip(dictionary.values(), dictionary.keys()))      # 将key和value互换生成新的reversed_dictionary
  return data, count, dictionary, reversed_dictionary

data, count, dictionary, reverse_dictionary = build_dataset(vocabulary, vocabulary_size)

del vocabulary                                                      # 删除原始单词列表，可以节约内存
print('Most common words (+UNK)', count[:5])                        # 打印vocabulary中最高频出现的词汇及其数量                            
print('Sample data', data[:10], [reverse_dictionary[i] for i in data[:10]])


# Step 3: 为skip-gram模型生成训练batch
data_index = 0
def generate_batch(batch_size, num_skips, skip_window):
  global data_index
  assert batch_size % num_skips == 0
  assert num_skips <= 2 * skip_window
  batch = np.ndarray(shape=(batch_size), dtype=np.int32)
  labels = np.ndarray(shape=(batch_size, 1), dtype=np.int32)
  span = 2 * skip_window + 1
  buffer = collections.deque(maxlen=span)
  if data_index + span > len(data):
    data_index = 0
  buffer.extend(data[data_index:data_index + span])
  data_index += span
  for i in range(batch_size // num_skips):
    context_words = [w for w in range(span) if w != skip_window]
    words_to_use = random.sample(context_words, num_skips)
    for j, context_word in enumerate(words_to_use):
      batch[i * num_skips + j] = buffer[skip_window]
      labels[i * num_skips + j, 0] = buffer[context_word]
    if data_index == len(data):
      buffer.extend(data[0:span])
      data_index = span
    else:
      buffer.append(data[data_index])
      data_index += 1
  data_index = (data_index + len(data) - span) % len(data)
  return batch, labels

batch, labels = generate_batch(batch_size=8, num_skips=2, skip_window=1)
for i in range(8):
  print(batch[i], reverse_dictionary[batch[i]],'->', labels[i, 0], reverse_dictionary[labels[i, 0]])


# Step 4: 建立和训练skip-gram模型
batch_size = 128
embedding_size = 128  # 词向量长度
skip_window = 1       # 上下文词语数
num_skips = 2
num_sampled = 64      # 负样本数量
valid_size = 16
valid_window = 100  # 选区100个高频词
valid_examples = np.random.choice(valid_window, valid_size, replace=False)

graph = tf.Graph()
with graph.as_default():
  train_inputs = tf.placeholder(tf.int32, shape=[batch_size])
  train_labels = tf.placeholder(tf.int32, shape=[batch_size, 1])
  valid_dataset = tf.constant(valid_examples, dtype=tf.int32)        # 将前面随机产生的valid_examples转为TensorFlow中的constant

  with tf.device('/cpu:0'):                                        # 限定所有计算在CPU上执行，因为有些操作在GPU上可能还没有实现
    embeddings = tf.Variable(
        tf.random_uniform([vocabulary_size, embedding_size], -1.0, 1.0))  # tf.random_uniform()随机生成所有单词的词向量embeddings
    embed = tf.nn.embedding_lookup(embeddings, train_inputs)              # tf.nn.embedding_lookup查找输入train_inputs对应的向量embed

    nce_weights = tf.Variable(
        tf.truncated_normal([vocabulary_size, embedding_size],
                            stddev=1.0 / math.sqrt(embedding_size)))     #  tf.truncated_normal初始化NCE loss中的权重参数nce_weigths
    nce_biases = tf.Variable(tf.zeros([vocabulary_size]))

# tf.nn.nce_loss计算学习出的词向量embedding在训练数据上的loss,然后使用tf.reduce_mean进行汇总
  loss = tf.reduce_mean(
      tf.nn.nce_loss(weights=nce_weights,
                     biases=nce_biases,
                     labels=train_labels,
                     inputs=embed,
                     num_sampled=num_sampled,
                     num_classes=vocabulary_size))

  # 定义优化器为SGD
  optimizer = tf.train.GradientDescentOptimizer(1.0).minimize(loss)

  norm = tf.sqrt(tf.reduce_sum(tf.square(embeddings), 1, keep_dims=True))
  normalized_embeddings = embeddings / norm
  valid_embeddings = tf.nn.embedding_lookup(
      normalized_embeddings, valid_dataset)
  similarity = tf.matmul(
      valid_embeddings, normalized_embeddings, transpose_b=True)

  init = tf.global_variables_initializer()


# Step 5: 开始训练
num_steps = 100001
with tf.Session(graph=graph) as session:
  init.run()
  print('Initialized')

  average_loss = 0
  for step in xrange(num_steps):
    batch_inputs, batch_labels = generate_batch(
        batch_size, num_skips, skip_window)
    feed_dict = {train_inputs: batch_inputs, train_labels: batch_labels}

    _, loss_val = session.run([optimizer, loss], feed_dict=feed_dict)
    average_loss += loss_val

    if step % 2000 == 0:
      if step > 0:
        average_loss /= 2000
      print('Average loss at step ', step, ': ', average_loss)
      average_loss = 0

    if step % 10000 == 0:
      sim = similarity.eval()
      for i in xrange(valid_size):
        valid_word = reverse_dictionary[valid_examples[i]]
        top_k = 8  # 最相近的8个词语
        nearest = (-sim[i, :]).argsort()[1:top_k + 1]
        log_str = 'Nearest to %s:' % valid_word
        for k in xrange(top_k):
          close_word = reverse_dictionary[nearest[k]]
          log_str = '%s %s,' % (log_str, close_word)
        print(log_str)
  final_embeddings = normalized_embeddings.eval()

# Step 6: 可视化词向量
def plot_with_labels(low_dim_embs, labels, filename):
  assert low_dim_embs.shape[0] >= len(labels), 'More labels than embeddings'
  plt.figure(figsize=(18, 18))
  for i, label in enumerate(labels):
    x, y = low_dim_embs[i, :]
    plt.scatter(x, y)
    plt.annotate(label,
                 xy=(x, y),
                 xytext=(5, 2),
                 textcoords='offset points',
                 ha='right',
                 va='bottom',
                 fontproperties=myfont)

  plt.savefig(filename)
  plt.show()

try:
  from sklearn.manifold import TSNE             # 实现降维，将原始的128维嵌入向量降到2维
  import matplotlib.pyplot as plt

  tsne = TSNE(perplexity=30, n_components=2, init='pca', n_iter=5000, method='exact')
  plot_only = 500
  low_dim_embs = tsne.fit_transform(final_embeddings[:plot_only, :])
  labels = [reverse_dictionary[i] for i in xrange(plot_only)]
  plot_with_labels(low_dim_embs, labels,  'tsne.png')

except ImportError as ex:
  print('Please install sklearn, matplotlib, and scipy to show embeddings.')
  print(ex)
