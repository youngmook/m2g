#!/usr/bin/env python

# Copyright 2014 Open Connectome Project (http://openconnecto.me)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# buildgraph.py
# Created by Disa Mhembere on 2015-02-27.
# Email: disa@jhu.edu
# Copyright (c) 2015. All rights reserved.

import os

from django.shortcuts import render_to_response
from django.template import RequestContext
from django.conf import settings
from django.http import HttpResponseRedirect
from pipeline.utils.util import get_script_prefix

from pipeline.forms import BuildGraphForm
from pipeline.utils.util import adaptProjNameIfReq, defDataDirs
from pipeline.utils.util import saveFileToDisk, sendJobBeginEmail
from pipeline.utils.create_dir_struct import create_dir_struct
from pipeline.models import BuildGraphModel
from pipeline.tasks import task_build

def buildGraph(request):

  error_msg = ""

  if request.method == "POST":
    form = BuildGraphForm(request.POST, request.FILES) # instantiating form
    if form.is_valid():

      # Acquire proj names
      proj_dir = form.cleaned_data["UserDefprojectName"]
      site = form.cleaned_data["site"]
      subject = form.cleaned_data["subject"]
      session = form.cleaned_data["session"]
      scanId = form.cleaned_data["scanId"]

      """
      # Private project error checking
      if (form.cleaned_data["Project_Type"] == "private"):
        if not request.user.is_authenticated():
          error_msg = "You must be logged in to make/alter a private project! \
              Please Login or make/alter a public project."

        # Untested TODO: Add join to ensure it a private project
        elif BuildGraphModel.objects.filter(owner=request.user, \
            project_name=proj_dir, site=site, subject=subject, \
            session=session, scanId=scanId).exists():

           error_msg = "The scanID you requested to create already \
               exists in this project path. Please change any of the form values."
      """
      if error_msg:
        return render_to_response(
          "buildgraph.html",
          {"buildGraphform": form, "error_msg": error_msg},
          context_instance=RequestContext(request)
          )

      """
      # If a user is logged in associate the project with thier directory
      if form.cleaned_data["Project_Type"] == "private":
        proj_dir = os.path.join(request.user.username, proj_dir)
      else:
      """
      proj_dir = os.path.join("public", proj_dir)

      # Adapt project name if necesary on disk
      proj_dir = adaptProjNameIfReq(os.path.join(
          settings.MEDIA_ROOT, proj_dir)) # Fully qualify AND handle identical projects

      usrDefProjDir = os.path.join(proj_dir, site, subject, session, scanId)
      """ Define data directory paths """
      derivatives, graphs = defDataDirs(usrDefProjDir)

      # Create a model object to save data to DB

      grModObj = BuildGraphModel(project_name = form.cleaned_data["UserDefprojectName"])
      grModObj.location = usrDefProjDir # The particular scan location

      grModObj.site = site
      grModObj.subject = subject
      grModObj.session = session
      grModObj.scanId = scanId

      if request.user.is_authenticated():
        grModObj.owner = request.user # Who created the project

      invariants = form.cleaned_data["invariants"]
      graph_size = form.cleaned_data["graph_size"]
      email = form.cleaned_data["email"]

      if graph_size == "big" and not email:
        return render_to_response(
          "buildgraph.html",
          {"buildGraphform": form, "error_msg": "Email address must be \
              provided when processing big graphs due to http timeout's possibly occurring."},
          context_instance=RequestContext(request)
          )

      """ Acquire fileNames """
      fiber_fn = form.cleaned_data["fiber_file"].name # get the name of the file input by user
      if form.cleaned_data["data_atlas_file"]:
        data_atlas_fn = form.cleaned_data["data_atlas_file"].name
        print "Storing data atlas ..."
        saveFileToDisk(form.cleaned_data["data_atlas_file"], 
            os.path.join(derivatives, data_atlas_fn))

      print "Storing fibers ..."
      """ Save files in appropriate location """
      saveFileToDisk(form.cleaned_data["fiber_file"], 
          os.path.join(derivatives, fiber_fn))
      grModObj.save() # Save project data to DB after file upload

      # add entry to owned project
      if request.user.is_authenticated():
        ownedProjModObj = OwnedProjects(project_name=grModObj.project_name, \
          owner=grModObj.owner, is_private=form.cleaned_data["Project_Type"] == "private")
        ownedProjModObj.save()

      print "\nSaving all files complete..."

      # Make appropriate dirs if they dont already exist
      create_dir_struct([derivatives, graphs])

      # TEST #
      """
      derivatives = "/home/disa/test/build_test"
      graphs = derivatives
      proj_dir = derivatives
      invariant_loc = derivatives 
      # END TEST #
      """

      sendJobBeginEmail(email, invariants)
      task_build.delay(derivatives, graphs, graph_size, invariants, derivatives, email)
      request.session["success_msg"] =\
"""
Your job successfully launched. You should receive an email to confirm launch
and another when it upon job completion. <br/>
<i>The process may take several hours</i> if you selected to compute all invariants.
"""
      return HttpResponseRedirect(get_script_prefix()+"success")

  else:
    form = BuildGraphForm() # An empty, unbound form

  # Render the form
  return render_to_response(
      "buildgraph.html",
      {"buildGraphform": form},
      context_instance=RequestContext(request) 
  )
