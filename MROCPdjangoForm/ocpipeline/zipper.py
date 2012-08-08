'''
@author : Disa Mhembere
Create a ZIP file on disk and transmit it in chunks of 8KB,                 
    without loading the whole file into memory.                            
'''

import os
import tempfile, zipfile
import argparse

def zipFilesFromFolders(dirName = None, multiTuple = []):
    '''
    dirName - any folder
    '''
    temp = tempfile.TemporaryFile()
    myzip = zipfile.ZipFile(temp ,'w', zipfile.ZIP_DEFLATED)
    
    
    if (multiTuple):
        for dirName in multiTuple:
            if dirName[0] != '.': # ignore metadata
                dirName = os.path.join(multiTuple, dirName)
                filesInOutputDir = os.listdir(dirName)
                
                for thefolder in filesInOutputDir:
                    if thefolder[0] != '.': # ignore metadata
                        dataProdDir = os.path.join(dirName, thefolder)
                        for thefile in os.listdir(dataProdDir):
                            filename =  os.path.join(dataProdDir, thefile)
                            myzip.write(filename, thefile) # second param of write determines name output
                            print "Compressing: " + thefile
        myzip.close()
        return temp
        
    
    filesInOutputDir = os.listdir(dirName)
    
    for thefolder in filesInOutputDir:
        if thefolder[0] != '.': # ignore metadata
            dataProdDir = os.path.join(dirName, thefolder)
            for thefile in os.listdir(dataProdDir):
                filename =  os.path.join(dataProdDir, thefile)
                myzip.write(filename, thefile) # second param of write determines name output
                print "Compressing: " + thefile

    myzip.close()
    #import pdb; pdb.set_trace()
    return temp

def main():
    
    parser = argparse.ArgumentParser(description='Zip the contents of an entire directory & place contents in single zip File')
    parser.add_argument('dirName', action='store')
    parser.add_argument('--multiTuple', action='store')
    
    result = parser.parse_args()
    
    zipFilesFromFolders(result.dirName, result.multiTuple)
    
if __name__ == '__main__':
    main()