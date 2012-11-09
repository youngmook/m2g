#!/usr/bin/python

# Author: Disa Mhembere, Johns Hopkins University
# Separated: 10/2/2012
# Plot all .np arrays in a common dir on the same axis & save
# 1 indexed

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pylab as pl

import numpy as np
import os
import sys
from glob import glob
import argparse
import scipy
from scipy import interpolate

# Issues: Done nothing with MAD

def plotInvDist(invDir, pngName, numBins =100):
  # ClustCoeff  Degree  Eigen  MAD  numEdges.npy  ScanStat  Triangle
  MADdir = "MAD"
  ccDir = "ClustCoeff"
  DegDir = "Degree"
  EigDir = "Eigen"
  SS1dir = "ScanStat"
  triDir = "Triangle"
  
  invDirs = [triDir, ccDir, SS1dir, DegDir ] 
  
  if not os.path.exists(invDir):
    print "%s does not exist" % invDir
    sys.exit(1)
  
  pl.figure(2)
  fig_gl, axes = pl.subplots(nrows=3, ncols=2)
  fig_gl.tight_layout()
  
  for idx, drcty in enumerate (invDirs):
    for arrfn in glob(os.path.join(invDir, drcty,'*.npy')): 
    #for arrfn in glob(os.path.join(invDir,'*.npy')):
      try:
        arr = np.load(arrfn)
        arr = np.log(arr[arr.nonzero()])
        print "Processing %s..." % arrfn
      except:
        print "Ivariant file not found %s"  % arrfn
      pl.figure(1)
      n, bins, patches = pl.hist(arr, bins=numBins , range=None, normed=False, weights=None, cumulative=False, \
               bottom=None, histtype='stepfilled', align='mid', orientation='vertical', \
               rwidth=None, log=False, color=None, label=None, hold=None)
  
      n = np.append(n,0)
      n = n/float(sum(n))
    
      fig = pl.figure(2)
      fig.subplots_adjust(hspace=.5)
      
      ax = pl.subplot(3,2,idx+1)
      
      if idx == 0:
        plt.axis([0, 35, 0, 0.04])
        ax.set_yticks(scipy.arange(0,0.04,0.01))
      if idx == 1 or idx == 2:
        ax.set_yticks(scipy.arange(0,0.03,0.01))
      if idx == 3:
        ax.set_yticks(scipy.arange(0,0.04,0.01))
      
      # Interpolation
      f = interpolate.interp1d(bins, n, kind='cubic') 
      
      x = np.arange(bins[0],bins[-1],0.03) # vary linspc
      
      interp = f(x)
      ltz = interp < 0
      interp[ltz] = 0
      pl.plot(x, interp,color ='grey' ,linewidth=1)
    
    if idx == 0:
      pl.ylabel('Probability')
      pl.xlabel('log number of local triangles')
    if idx == 1:
      #pl.ylabel('Probability')
      pl.xlabel('log local clustering coefficient')
    if idx == 2:
      pl.ylabel('Probability')
      pl.xlabel('log scan1')
    if idx == 3:
      #pl.ylabel('Probability')
      pl.xlabel('log local degree')
  
  ''' Eigenvalues '''
  
  ax = pl.subplot(3,2,5)
  ax.set_yticks(scipy.arange(0,180000,40000))
  for eigValInstance in glob(os.path.join(invDir, EigDir,"*.npy")):
    try:
      eigv = np.load(eigValInstance)
    except:
      print "Eigenvalue array"
    
    n = len(eigv)
    pl.plot(range(1,n+1), np.sort(eigv), color='grey')
    pl.ylabel('Magnitude')
    pl.xlabel('Eigenvalue rank in top 100')
    
  ''' Edges '''
  
  arrfn = os.path.join(invDir, 'numEdges.npy')
  try:
    arr = np.load(arrfn)
    arr = np.log(arr[arr.nonzero()])
    print "Processing %s..." % arrfn
  except:
    print "Ivariant file not found %s"  % arrfn
  pl.figure(1)
  n, bins, patches = pl.hist(arr, bins=10 , range=None, normed=False, weights=None, cumulative=False, \
           bottom=None, histtype='stepfilled', align='mid', orientation='vertical', \
           rwidth=None, log=False, color=None, label=None, hold=None)

  n = np.append(n,0)
  
  
  fig = pl.figure(2)
  ax = pl.subplot(3,2,5)
  
  f = interpolate.interp1d(bins, n, kind='cubic') 
  x = np.arange(bins[0],bins[-1],0.03) # vary linspc
  
  interp = f(x)
  ltz = interp < 0
  interp[ltz] = 0
  pl.plot(x, interp,color ='grey' ,linewidth=1)
  pl.ylabel('Frequency')
  pl.xlabel('log global edge number')
    
  pl.savefig(pngName) 
  #pl.savefig(os.path.join(toDir, "CombinedTriangles.png")) 
  
def main():
    
    parser = argparse.ArgumentParser(description='Plot distribution of invariant arrays of several graphs')
    parser.add_argument('invDir', action='store',help='The full path of directory containing .npy invariant arrays')
    parser.add_argument('pngName', action='store', help='Full path of directory of resulting png file')
    parser.add_argument('numBins', type = int, action='store', help='Number of bins')
    
    result = parser.parse_args()
    
    plotInvDist(result.invDir, result.pngName, result.numBins)

if __name__ == '__main__':
  main()
  
