#!/usr/bin/python

"""
@author : Disa Mhembere
@organization: Johns Hopkins University
@contact: disa@jhu.edu

@summary: Module to hold the views of a Django one-click MR-connectome pipeline
"""

import os, sys, re
from glob import glob
import threading
from random import randint
os.environ["MPLCONFIGDIR"] = "/tmp/"

import zipfile
import tempfile

from django.shortcuts import render_to_response
from django.template import RequestContext
from django.http import HttpResponseRedirect
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.shortcuts import render

from django.core.files import File        # For programmatic file upload

# Model & Form imports
from models import BuildGraphModel
from models import OwnedProjects
from forms import DownloadForm
from forms import GraphUploadForm
from forms import ConvertForm
from forms import BuildGraphForm
from forms import PasswordResetForm

import mrpaths

""" Data Processing imports"""
from mrcap import gengraph as gengraph
import mrcap.svd as svd
import mrcap.lcc as lcc

import filesorter as filesorter
import utils.zipper as zipper
from utils.createDirStruct import createDirStruct
from computation.utils.convertTo import convert_graph

from django.core.servers.basehttp import FileWrapper

import subprocess
from django.core.urlresolvers import get_script_prefix
from django.conf import settings

from time import strftime, localtime
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.shortcuts import redirect

""" Auth imports """
from django.contrib.auth.decorators import login_required

####################
## Graph Analysis ##
####################
import computation.composite.invariants as cci
import scipy.io as sio

# Registration
from django.contrib.auth import authenticate, login, logout

# Helpers
from utils.util import *

""" Base url just redirects to welcome """
def default(request):
  return redirect(get_script_prefix()+"welcome", {"user":request.user})

""" Little welcome message """
def welcome(request):
  return render_to_response("welcome.html", {"user":request.user},
                            context_instance=RequestContext(request))

""" Successful completion of task"""
def success(request):
  return render_to_response("success.html", {"msg": request.session["success_msg"]}
                            ,context_instance=RequestContext(request))

""" Job failure """
def jobfailure(request):
  return render_to_response("job_failure.html", {"msg": "Please check that your fiber streamline file and ROI's are correctly formatted"}
                            ,context_instance=RequestContext(request))

# Login decorator
#@login_required(redirect_field_name="my_redirect_field")
#@login_required # OR EASIER
def buildGraph(request):

  error_msg = ""

  if request.method == "POST":
    form = BuildGraphForm(request.POST, request.FILES) # instantiating form
    if form.is_valid():

      # Acquire proj names
      userDefProjectName = form.cleaned_data["UserDefprojectName"]
      site = form.cleaned_data["site"]
      subject = form.cleaned_data["subject"]
      session = form.cleaned_data["session"]
      scanId = form.cleaned_data["scanId"]

      # Private project error checking
      if (form.cleaned_data["Project_Type"] == "private"):
        if not request.user.is_authenticated():
          error_msg = "You must be logged in to make/alter a private project! Please Login or make/alter a public project."

        """
        # Untested TODO: Add join to ensure it a private project
        elif BuildGraphModel.objects.filter(owner=request.user, project_name=userDefProjectName, \
                                    site=site, subject=subject, session=session, scanId=scanId).exists():

           error_msg = "The scanID you requested to create already exists in this project path. Please change any of the form values."
        """
      # TODO DM: Some unaccounted for scenarios here!

      if error_msg:
        return render_to_response(
          "buildgraph.html",
          {"buildGraphform": form, "error_msg": error_msg},
          context_instance=RequestContext(request)
          )

      # If a user is logged in associate the project with thier directory
      if form.cleaned_data["Project_Type"] == "private":
        userDefProjectName = os.path.join(request.user.username, userDefProjectName)
      else:
        userDefProjectName = os.path.join("public", userDefProjectName)

      # Adapt project name if necesary on disk
      userDefProjectName = adaptProjNameIfReq(os.path.join(settings.MEDIA_ROOT, userDefProjectName)) # Fully qualify AND handle identical projects

      request.session["usrDefProjDir"] = os.path.join(userDefProjectName, site, subject, session, scanId)
      request.session["scanId"] = scanId

      """ Define data directory paths """
      request.session["derivatives"], request.session["graphs"],\
          request.session["graphInvariants"] = defDataDirs(request.session["usrDefProjDir"])

      # Create a model object to save data to DB

      grModObj = BuildGraphModel(project_name = form.cleaned_data["UserDefprojectName"])
      grModObj.location = request.session["usrDefProjDir"] # Where the particular scan location is

      grModObj.site = form.cleaned_data["site"]# set the site
      grModObj.subject = form.cleaned_data["subject"]# set the subject
      grModObj.session = form.cleaned_data["session"]# set the session
      grModObj.scanId = form.cleaned_data["scanId"]# set the scanId

      if request.user.is_authenticated():
        grModObj.owner = request.user # Who created the project

      request.session["invariants"] = form.cleaned_data["Select_Invariants_you_want_computed"]
      request.session["graphsize"] = form.cleaned_data["Select_graph_size"]
      request.session["email"] = form.cleaned_data["Email"]

      if request.session["graphsize"] == "big" and not request.session["email"]:
        return render_to_response(
          "buildgraph.html",
          {"buildGraphform": form, "error_msg": "Email address must be provided when processing big graphs due to http timeout's possibly occuring."},
          context_instance=RequestContext(request)
          )

      """ Acquire fileNames """
      fiber_fn = form.cleaned_data["fiber_file"].name # get the name of the file input by user
      roi_raw_fn = form.cleaned_data["roi_raw_file"].name
      roi_xml_fn = form.cleaned_data["roi_xml_file"].name

      print "Uploading files..."


      """ Save files in appropriate location """
      saveFileToDisk(form.cleaned_data["fiber_file"], os.path.join(request.session["derivatives"], fiber_fn))
      saveFileToDisk(form.cleaned_data["roi_raw_file"], os.path.join(request.session["derivatives"], roi_raw_fn))
      saveFileToDisk(form.cleaned_data["roi_xml_file"], os.path.join(request.session["derivatives"], roi_xml_fn))

      grModObj.save() # Save project data to DB after file upload

      # add entry to owned project
      if request.user.is_authenticated():
        ownedProjModObj = OwnedProjects(project_name=grModObj.project_name, \
          owner=grModObj.owner, is_private=form.cleaned_data["Project_Type"] == "private")
        ownedProjModObj.save()

      print "\nSaving all files complete..."

      """ Make appropriate dirs if they dont already exist """
      createDirStruct([request.session["derivatives"],\
          request.session["graphs"], request.session["graphInvariants"]])

      if request.session["graphsize"] == "big":
        # Launch thread for big graphs & email user
        #processInputData(request)
        sendJobBeginEmail(request.session["email"], request.session["invariants"])
        thr = threading.Thread(target=processInputData, args=(request,))
        thr.start()
        request.session["success_msg"] =\
"""
Your job was successfully launched. You should receive an email when your
job begins and another one when it completes. The process may take several if you selected to compute all invariants
"""
        return HttpResponseRedirect(get_script_prefix()+"success")

      # Redirect to Processing page
      return HttpResponseRedirect(get_script_prefix()+"processinput")
  else:
    form = BuildGraphForm() # An empty, unbound form

  # Render the form
  return render_to_response(
      "buildgraph.html",
      {"buildGraphform": form},
      context_instance=RequestContext(request) # Some failure to input data & returns a key signaling what is requested
  )

def processInputData(request):
  '''
  Extract File name & determine what file corresponds to what for gengraph
  @param request: the request object
  '''
  filesInUploadDir = os.listdir(request.session['derivatives'])

  roi_xml_fn, fiber_fn, roi_raw_fn = filesorter.checkFileExtGengraph(filesInUploadDir) # Check & sort files

  ''' Fully qualify file names '''
  fiber_fn = os.path.join(request.session['derivatives'], fiber_fn)
  roi_raw_fn = os.path.join(request.session['derivatives'], roi_raw_fn)
  roi_xml_fn = os.path.join(request.session['derivatives'], roi_xml_fn)

  try:
    request.session['Gfn']= call_gengraph(fiber_fn, roi_xml_fn, roi_raw_fn, \
                              request.session['graphs'], request.session['graphInvariants'],\
                              request.session['graphsize'], True)
  except:
    if request.session['graphsize'] == 'big':
      msg = "Hello,\n\nYour most recent job failed either because your fiber streamline file or ROI mask was incorrectly formatted."
      msg += " Please check both and try again.%s\n\n" % (" "*randint(0,10))
      sendJobFailureEmail(request.session['email'], msg)
    return HttpResponseRedirect(get_script_prefix()+"jobfailure")

  # Run ivariants here
  if len(request.session['invariants']) > 0:
    print "Computing invariants ..."

    request.session['invariant_fns'] = runInvariants(request.session['invariants'],\
                                request.session['Gfn'], request.session['graphInvariants'])

  if request.session['graphsize'] == 'big':
    dwnldLoc = request.META['wsgi.url_scheme'] + '://' + \
                    request.META['HTTP_HOST'] + request.session['usrDefProjDir'].replace(' ','%20')
    sendJobCompleteEmail(request.session['email'], dwnldLoc)

  return HttpResponseRedirect(get_script_prefix()+'confirmdownload')

def confirmDownload(request):

  if request.method == 'POST':
    form = DownloadForm(request.POST) # instantiating form
    if form.is_valid():

      dataReturn = form.cleaned_data['Select_output_type']

      if dataReturn == 'vd': # View data directory
        dataUrlTail = request.session['usrDefProjDir']

        dwnldLoc = request.META['wsgi.url_scheme'] + '://' + \
                    request.META['HTTP_HOST'] + dataUrlTail.replace(' ','%20')

        return HttpResponseRedirect(dwnldLoc)

      elif dataReturn == 'dz': #Download all as zip
        return HttpResponseRedirect(get_script_prefix()+'zipoutput')
  else:
    form = DownloadForm()
  return render_to_response('confirmDownload.html',{'downloadForm': form},\
                  context_instance=RequestContext(request))

#################################################################################

def getRootUrl(request):
  return request.META['wsgi.url_scheme'] + '://' + request.META['HTTP_HOST']

@login_required
def showdir(request):
  #directory = request.session['usrDefProjDir']
  return render('STUB')

def contact(request):
  return render_to_response('contact.html')


#################################################################################
def zipProcessedData(request):
  '''
  Compress data products to single zip for upload
  @param request: the request object
  '''
  print '\nBeginning file compression...'
  # Take dir with multiple scans, compress it & send it off

  ''' Zip it '''
  #temp = zipper.zipFilesFromFolders(dirName = request.session['usrDefProjDir'])
  temp = zipper.zipper(request.session['usrDefProjDir'], zip_file = request.session['usrDefProjDir'] + '.zip')
  ''' Wrap it '''
  wrapper = FileWrapper(temp)
  response = HttpResponse(wrapper, content_type='application/zip')
  response['Content-Disposition'] = ('attachment; filename='+ request.session['scanId'] +'.zip')
  response['Content-Length'] = temp.tell()
  temp.seek(0)

  ''' Send it '''
  return response

def upload(request, webargs=None):
  """
  Programmatic interface for uploading data
  @param request: the request object

  @param webargs: POST data with userDefProjectName, site, subject, session, scanId, graphsize, [list of invariants to compute] info
  """
  if (webargs and request.method == 'POST'):
    # Check for malformatted input
    webargs = webargs[1:] if webargs.startswith('/') else webargs
    webargs = webargs[:-1] if webargs.endswith('/') else webargs

    if len(webargs.split('/')) == 7:
      [userDefProjectName, site, subject, session, scanId, graphsize, request.session['invariants']] = webargs.split('/')

      request.session['invariants'] = request.session['invariants'].split(',')
    elif len(webargs.split('/')) == 6:
      [userDefProjectName, site, subject, session, scanId, graphsize] = webargs.split('/')
    else:
      # Some sort of error
      return HttpResponseBadRequest ("Malformatted programmatic request. Check format of url and data requests")

    userDefProjectDir = adaptProjNameIfReq(os.path.join(settings.MEDIA_ROOT, 'public', userDefProjectName, site, subject, session, scanId))

    ''' Define data directory paths '''
    derivatives, graphs, request.session['graphInvariants'] = defDataDirs(userDefProjectDir)

    ''' Make appropriate dirs if they dont already exist '''
    createDirStruct([derivatives, graphs,request.session["graphInvariants"]])
    print 'Directory structure created...'

    uploadFiles =  writeBodyToDisk(request.body, derivatives)

    # Check which file is which
    roi_xml_fn, fiber_fn, roi_raw_fn = filesorter.checkFileExtGengraph(uploadFiles) # Check & sort files

    ''' Data Processing '''
    if graphsize:
      request.session['Gfn']= call_gengraph(fiber_fn, roi_xml_fn, roi_raw_fn, \
                              graphs, request.session['graphInvariants'],\
                              graphsize, run=True)

    else:
      return HttpResponseBadRequest ("Missing graph size. You must specify big or small")


    # Run invariants
    if request.session.has_key('invariants'):
      print "Computing invariants ..."

      invariant_fns = runInvariants(request.session['invariants'],\
                      request.session['Gfn'], request.session['graphInvariants'])

    dwnldLoc = request.META['wsgi.url_scheme'] + '://' + \
                    request.META['HTTP_HOST'] + userDefProjectDir.replace(' ','%20')

    return HttpResponse ( "Files available for download at " + dwnldLoc) # change to render of a page with a link to data result

  elif(not webargs):
    return HttpResponseBadRequest ("Expected web arguments to direct project correctly")

  else:
    return HttpResponseBadRequest ("Expected POST data, but none given")

################## TO DOs ########################
def download(request, webargs=None):
  base_dir = "/data/projects/disa/OCPprojects/tmp/graphs"
  mouse_dir = os.path.join(base_dir, )

###################################################

def asyncInvCompute(request):

  dwnldLoc = request.META['wsgi.url_scheme'] + '://' + \
                    request.META['HTTP_HOST'] + request.session['dataDir'].replace(' ','%20')

  for graph_fn in request.session['uploaded_graphs']:
    try:
      invariant_fns = runInvariants(request.session['invariants'], graph_fn,
                      request.session['graphInvariants'], graph_format=request.session['graph_format'])

      print 'Invariants for annoymous project %s complete...' % graph_fn

    except Exception, msg:
      msg = """
Hello,\n\nYour most recent job failed possibly because:\n- the graph '%s' you
uploaded does not match any accepted type.\n\n"You may have some partially
completed data here: %s.\nPlease check these and try again.\n\n
""" % (os.path.basename(graph_fn), dwnldLoc)

      sendJobFailureEmail(request.session['email'], msg)

  # Email user of job finished
  sendJobCompleteEmail(request.session['email'], dwnldLoc)

#########################################
#	*******************		#
#	   GRAPH LOAD VIEW		#
#########################################
def graphLoadInv(request, webargs=None):
  ''' Form '''
  if request.method == 'POST' and not webargs:
    form = GraphUploadForm(request.POST, request.FILES) # instantiating form
    if form.is_valid():

      request.session['graphsize'] = 'small' # This accounts for use LCC or not
      request.session['email'] =  form.cleaned_data['email']

      data = form.files['fileObj'] # get data
      request.session['invariants'] = form.cleaned_data['Select_Invariants_you_want_computed']

      dataDir = os.path.join(settings.MEDIA_ROOT, 'tmp', strftime("projectStamp%a%d%b%Y_%H.%M.%S/", localtime()))
      request.session['graphInvariants'] = os.path.join(dataDir, 'graphInvariants')

      makeDirIfNone([dataDir])

      # We got a zip
      if os.path.splitext(data.name)[1] == '.zip':
        writeBodyToDisk(data.read(), dataDir)
        graphs = glob(os.path.join(dataDir,'*')) # TODO: better way to make sure we are actually collecting graphs here

      else: # View only accepts .mat & zip as regulated by template
        graphs = [os.path.join(dataDir, data.name)]
        saveFileToDisk(data, graphs[0])

      request.session['uploaded_graphs'] = graphs
      request.session['graph_format'] = form.cleaned_data['graph_format']
      request.session['dataDir'] = dataDir
      request.session['email'] = form.cleaned_data['email']

      # Launch thread for graphs & email user
      sendJobBeginEmail(request.session['email'], request.session['invariants'], genGraph=False)

      thr = threading.Thread(target=asyncInvCompute, args=(request,))
      thr.start()

      request.session['success_msg'] = \
"""
Your job was successfully launched. You should receive an email when your  job begins and another one when it completes.
The process may take several hours per graph (dependent on graph size) if you selected to compute all invariants.
If you do not see an email in your INBOX check the SPAM folder and add jhmrocp@cs.jhu.edu to your safe list.
"""
      return HttpResponseRedirect(get_script_prefix()+'success')

  # Programmatic RESTful API
  elif request.method == 'POST' and webargs:
    dataDir = os.path.join(settings.MEDIA_ROOT, 'tmp', strftime("projectStamp%a%d%b%Y_%H.%M.%S/", localtime()))
    makeDirIfNone([dataDir])

    uploadedZip = writeBodyToDisk(request.body, dataDir)[0] # Not necessarily a zip

    try: # Assume its a zip first
      zipper.unzip(uploadedZip, dataDir) # Unzip the zip
      os.remove(uploadedZip) # Delete the zip
    except:
      print "Non-zip file uploaded ..."
    graphs = glob(os.path.join(dataDir,'*'))

    try:
      request.session['invariants'] = webargs.split('/')[0].split(',')
      inGraphFormat = webargs.split('/')[1]
    except:
      return HttpResponse("Malformated input invariants list or graph format")

    request.session['graphInvariants'] = os.path.join(dataDir, 'graphInvariants')

    for graph_fn in graphs:
      invariant_fns = runInvariants(request.session['invariants'], graph_fn,
                        request.session['graphInvariants'], inGraphFormat)
      print 'Computing Invariants for annoymous project %s complete...' % graph_fn

      err_msg=""
      if len(webargs.split('/')) > 2:
        err_msg = "" # __init__
        err_msg = convert_graph(invariant_fns["out_graph_fn"], "graphml",
                request.session['graphInvariants'], *webargs.split('/')[2].split(','))

      dwnldLoc = request.META['wsgi.url_scheme'] + '://' + \
                    request.META['HTTP_HOST'] + dataDir.replace(' ','%20')
      if err_msg:
        err_msg = "Completed with errors. View Data at: %s\n. Here are the errors:%s" % (dwnldLoc, err_msg)
        return HttpResponse(err_msg)

    return HttpResponse("View Data at: " + dwnldLoc)
  # Browser
  else:
    form = GraphUploadForm() # An empty, unbound form

  # Render the form
  return render_to_response(
      'graphupload.html',
      {'graphUploadForm': form},
      context_instance=RequestContext(request) # Some failure to input data & returns a key signaling what is requested
  )

#########################################
#	*******************		#
#	  CONVERT GRAPH FORMAT		#
#########################################

def convert(request, webargs=None):
  ''' Form '''

  if (request.method == 'POST' and not webargs):
    form = ConvertForm(request.POST, request.FILES) # instantiating form
    if form.is_valid():

      baseDir = os.path.join(settings.MEDIA_ROOT, 'tmp', strftime('formUpload%a%d%b%Y_%H.%M.%S/', localtime()))
      saveDir = os.path.join(baseDir,'upload') # Save location of original uploads
      convertFileSaveLoc = os.path.join(baseDir,'converted') # Save location of converted data

      if not (os.path.exists(convertFileSaveLoc)):
        os.makedirs(convertFileSaveLoc)

      savedFile = os.path.join(saveDir, request.FILES['fileObj'].name)

      saveFileToDisk(request.FILES['fileObj'], savedFile)

      # If zip is uploaded
      if os.path.splitext(request.FILES['fileObj'].name)[1].strip() == '.zip':
        zipper.unzip(savedFile, saveDir)
        # Delete zip so its not included in the graphs we uploaded
        os.remove(savedFile)
        uploadedFiles = glob(os.path.join(saveDir, "*")) # get the uploaded file names

      else:
        uploadedFiles = [savedFile]

      err_msg=""
      for fn in uploadedFiles:
        err_msg = convert_graph(fn, form.cleaned_data['input_format'],
                        convertFileSaveLoc, *form.cleaned_data['output_format'])

      dwnldLoc = request.META['wsgi.url_scheme'] + '://' + \
                    request.META['HTTP_HOST'] + convertFileSaveLoc.replace(' ','%20')

      if (err_msg):
        err_msg = "Your job completed with errors. The result can be found at %s\n. Here are the errors:%s" % (dwnldLoc, err_msg)
        return render_to_response(
        'convertupload.html',
        {'convertForm': form, 'err_msg': err_msg+"\n"},
        context_instance=RequestContext(request))
      #else
      return HttpResponseRedirect(dwnldLoc)

  elif(request.method == 'POST' and webargs):
    # webargs is {inFormat}/{outFormat}
    inFormat = webargs.split('/')[0] # E.g 'graphml'| 'dot' | 'leda'
    outFormat =  webargs.split('/')[1].split(',')

    outFormat = list(set(outFormat)) # Eliminate duplicates if any exist

    baseDir = os.path.join(settings.MEDIA_ROOT, 'tmp', strftime('progUpload%a%d%b%Y_%H.%M.%S/', localtime()))
    saveDir = os.path.join(baseDir,'upload') # Save location of original uploads
    convertFileSaveLoc = os.path.join(baseDir,'converted') # Save location of converted data

    if not os.path.exists(saveDir): os.makedirs(saveDir)
    if not os.path.exists(convertFileSaveLoc): os.makedirs(convertFileSaveLoc)

    uploadedFiles = writeBodyToDisk(request.body, saveDir)# can only be one file # TODO: Check me

    # Check for zip
    if os.path.splitext(uploadedFiles[0])[1].strip() == '.zip':
        zipper.unzip(uploadedFiles[0], saveDir)
        # Delete zip so its not included in the graphs we uploaded
        os.remove(uploadedFiles[0])
        uploadedFiles = glob(os.path.join(saveDir, "*")) # get the uploaded file names

    err_msg = ""
    for fn in uploadedFiles:
      err_msg = convert_graph(fn, inFormat,
                        convertFileSaveLoc, *outFormat)

    dwnldLoc = request.META['wsgi.url_scheme'] + '://' + \
                    request.META['HTTP_HOST'] + convertFileSaveLoc.replace(' ','%20')

    if err_msg:
      err_msg = "Completed with errors. View Data at: %s\n. Here are the errors:%s" % (dwnldLoc, err_msg)
      return HttpResponse(err_msg)

    return HttpResponse ( "Converted files available for download at " + dwnldLoc + " . The directory " +
            "may be empty if you try to convert from, and to the same format.") # change to render of a page with a link to data result

  else:
    form = ConvertForm() # An empty, unbound form

  # Render the form
  return render_to_response(
      'convertupload.html',
      {'convertForm': form},
      context_instance=RequestContext(request))

#########################################
#	*******************		#
#	   PROCESS DATA			#
#########################################

def call_gengraph(fiber_fn, roi_xml_fn, roi_raw_fn, graphs, graphInvariants, graphsize, run = False):
  '''
  Run graph building and other related scripts
  @param fiber_fn: fiber tract file
  @param roi_xml_fn: region of interest xml file
  @param roi_raw_fn: region of interest raw file

  @param graphs: Dir where biggraphs & smallgraphs are saved
  @param graphInvariants:  Dir where graph invariants are saved
  @param graphsize: the size of the graph 'big' or 'small'
  @param run: Whether or not to run processor intensive jobs. Default is - false so nothing is actually run
  '''

  baseName = getFiberID(fiber_fn) #VERY TEMPORARY

  Gfn = os.path.join(graphs, baseName) # partial name

  if (run):
    if graphsize.lower().startswith("s"):
      print("Running Small gengraph ...")
      Gfn+="smgr.graphml"
      gengraph.genGraph(fiber_fn, Gfn, roi_xml_fn, roi_raw_fn, bigGraph=False)

    elif graphsize.lower().startswith("b"):
      print("\nRunning Big gengraph ...")
      Gfn+="bggr.graphml"
      gengraph.genGraph(fiber_fn, Gfn, roi_xml_fn, roi_raw_fn, bigGraph=True)
    else:
      print '[ERROR]: Graphsize Unkwown' # should never happen
  return Gfn

###############################################################################
#                          NEW INVARIANTS                                     #
###############################################################################

def runInvariants(inv_list, graph_fn, save_dir, graph_format="graphml", sep_save=False):
  '''
  Run the selected multivariate invariants as defined

  @param inv_list: the list of invariants we are to compute
  @param graph_fn: the graph filename on disk
  @param save_dir: the directory where to save resultant data

  @param graph_format: the format of the graph
  @param sep_save: boolean on whether to save invariants in separate files
  '''
  inv_dict = {'graph_fn':graph_fn, 'save_dir':save_dir}
  for inv in inv_list:
    inv_dict[inv] = True

  inv_dict = cci.compute(inv_dict, sep_save=sep_save, gformat=graph_format)

  if isinstance(inv_dict, str):
    return inv_dict # Error message
  else:
    inv_dict = inv_dict[1]

  return_dict = dict()

  for key in inv_dict:
    if key.endswith("_fn") and not key.startswith("eig"): # skip eigs
      return_dict[key] = inv_dict[key]

  if inv_dict.get("eigvl_fn", None): # or "eigvect_fn"
    return_dict["eig"] = [inv_dict["eigvect_fn"], inv_dict["eigvl_fn"]] # Note this

  return return_dict
