#!/usr/bin/env python

##############################################################################################
# Import packages needed
import argparse
import time
import subprocess
from subprocess import *
import pandas as pd
import numpy as np
from numpy import *
from dfply import *
import io
from io import StringIO
from io import *


import multiprocessing
##############################################################################################
### time calculation
start_time=time.clock()

# Reform vcf file
### input each sample genotype
### For GT Format:
###  code '0|0' or '0/0' as 0
###  code ('0|1' or '1|0')  or ('0/1' or '1/0') as 1
###  code '1|1' or '1/1' as 2
###  code '.|.' or './.' as nan(missing)

### For DS Format:
### code '.' as nan(missing)
def geno_reform(data,Format):
    if Format=='GT':
        data[(data=='0|0')|(data=='0/0')]=0
        data[(data=='1|0')|(data=='1/0')|(data=='0|1')|(data=='0/1')]=1
        data[(data=='1|1')|(data=='1/1')]=2
        data[(data=='.|.')|(data=='./.')]=nan
    elif Format=='DS':
        data[(data==".")]=nan
    return data

### For vcf input
### Split input dataframe by Format. ex, '0|0:0.128'
### Input:
### 1. data:The first nine columns fixed
### 2. Format: GT or DS

### Output:
###  The First six columns of output dataframe should be:
###    1) CHROM
###    2) POS
###    3) ID (i.e. rsID)
###    4) REF
###    5) ALT
###    6) snpID (CHROM:POS:REF:ALT)
###    7) p_HWE:p-value for Hardy Weinberg Equilibrium exact test
###    8) MAF: Minor Allele Frequency (range from 0~1)
###    9) Samples gene variance splited by Format (GT or DS)

def CHR_Reform_vcf(data,Format,maf):
    sampleID = data.columns[9:]

    data['snpID']=(data['CHROM'].astype('str')+":"+data['POS'].astype('str')
                   +":"+data.REF+":"+data.ALT)
        
    CHR = data >> select(data[['CHROM','POS','ID','REF','ALT','snpID']],data[sampleID])

    CHR=CHR.drop_duplicates(['snpID'],keep='first')
        
    indicate=data.FORMAT[0].split(":").index(Format)
    CHR[sampleID]=CHR[sampleID].applymap(lambda x:x.split(":")[indicate])
    
    CHR[sampleID]=CHR[sampleID].apply(lambda x:geno_reform(x,Format),axis=0)

    ### calculate MAF by SNPs(range from 0-1)
    temp=pd.DataFrame((CHR >> select(CHR[sampleID])),dtype=np.float)
    CHR['MAF']=temp.apply(lambda x:sum(x)/(2*len(x.dropna())),axis=1)

    ### Dealing with NaN
    CHR[np.hstack(([sampleID,'MAF']))] = CHR[np.hstack(([sampleID,'MAF']))].apply(lambda x:x.fillna(2*x.MAF),axis=1)
    
    return (CHR>>mask(CHR.MAF>maf)),sampleID

### For dosages input
### Input:
### 1. data:The first five columns fixed
###    1) CHROM
###    2) POS
###    3) ID (i.e. rsID)
###    4) REF
###    5) ALT
### 2. Format: DS

def CHR_Reform_DS(data,maf):
    sampleID=data.columns[5:]
    
    data['snpID']=(data['CHROM'].astype('str')+':'+data['POS'].astype('str')
                   +':'+data.REF+':'+data.ALT)
    data=data.drop_duplicates(['snpID'],keep='first')

    data[data[sampleID].astype('str')=='.']=nan
    
    data[sampleID]=data[sampleID].astype('float')

    data['MAF']=data[sampleID].apply(lambda x:sum(x)/(2*len(x.dropna())),axis=1)
    
    data[np.hstack(([sampleID,'MAF']))] = data[np.hstack(([sampleID,'MAF']))].apply(lambda x:x.fillna(2*x.MAF),axis=1)
    
    return (data>>mask(data.MAF>maf)),sampleID

######################################################################################
### variable needed
parser = argparse.ArgumentParser(description='manual to this script')

### chromosome block information
parser.add_argument('--block',type=str,default = None)

### genotype file dir
parser.add_argument('--geno_path',type=str,default = None)

### specified input file type(vcf or dosages)
parser.add_argument('--geno',type=str,default = None)

### chromosome number
parser.add_argument('--chr_num',type=int,default = None)

### 'DS' or 'GT'
parser.add_argument('--Format',type=str,default = None)

### maf threshold for seleting genotype data to calculate covariance matrix
parser.add_argument('--maf',type=float,default = None)

### number of thread
parser.add_argument('--thread',type=int,default = None)

### output dir
parser.add_argument('--out_prefix',type=str,default = None)

args = parser.parse_args()

######################################################################################
### variable checking
print("Block information:"+args.block)
print("Genotype file:"+args.geno_path)

if args.geno=='vcf':
	print("Using "+args.Format+" Format for association study.")
elif args.geno=='dosage':
	print("Using DS format for association study.")
else:
	raise SystemExit("Geno file can not identify.")

print("Chromosome number:"+str(args.chr_num))
print("Number of thread:"+str(args.thread))
print("Threshold of maf value:"+str(args.maf))
print("Output dir:"+args.out_prefix)

#######################################################################################
### Read in block information
Block = pd.read_csv(args.block,sep='\t')

Block = Block >> mask(Block.CHROM==args.chr_num)
Block = Block.reset_index(drop=True)

file_path=args.geno_path+'/'+unique(Block.File)[0]

header_process = subprocess.Popen(["zcat"+" "+file_path+"|"+"grep"+" "+"'CHROM'"],
                                  shell=True,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
header=header_process.communicate()[0]

pd.DataFrame(columns=['CHROM', 'POS', 'ID', 'REF', 'ALT','COV']).to_csv(args.out_prefix+'/CHR'+str(args.chr_num)+'_reference_cov.txt',
                                                                        sep='\t',index=None,header=True)

def thread_process(num):
    block_temp = Block.loc[num]
    
    ### select corresponding genotype file by tabix
    chr_process=subprocess.Popen(["tabix"+" "+file_path+" "+str(block_temp.CHROM)+":"+str(block_temp.Start)+"-"+str(block_temp.End)],
                                 shell=True,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
    out=chr_process.communicate()[0]

    if len(out)==0:
        print("No corresponding genotype data in this block.")
    else:
        CHR = pd.read_csv(StringIO(out.decode('utf-8')),sep='\t',low_memory=False)
        CHR.columns = (pd.read_csv(StringIO(header.decode('utf-8')),sep='\t',low_memory=False)).columns
        CHR = CHR.rename(columns={'#CHROM':'CHROM'})
        CHR = CHR.reset_index(drop=True)

    if args.geno=='vcf':
        if args.Format not in unique(CHR.FORMAT)[0].split(':'):
            print("Format needed is not provided in input file.")
        else:
            Chrom,sampleID = CHR_Reform_vcf(CHR,args.Format,args.maf)
    elif args.geno=='dosages':
        Chrom,sampleID = CHR_Reform_DS(CHR,args.maf)
    
    Chrom = Chrom.sort_values(by='POS')
    Chrom = Chrom.reset_index(drop=True)

    mcovar = cov(pd.DataFrame(Chrom[sampleID],dtype='float'))

    for i in range(len(Chrom)):
        covar_info=np.append([Chrom.loc[i][0:5].ravel()],','.join(mcovar[i,i:].astype('str')))

        pd.DataFrame(covar_info).T.to_csv(args.out_prefix+'/CHR'+str(args.chr_num)+'_reference_cov.txt',
                                          sep='\t',index=None,header=None,mode='a')

########################################################################################################
### thread process
pool = multiprocessing.Pool(args.thread)

pool.map(thread_process,[num for num in range(len(Block))])

pool.close()
pool.join()

#########################################################################################################
### time calculation
time=round((time.clock()-start_time)/60,2)

print(str(time)+' minutes')














