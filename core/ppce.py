###############################################################
# Probabilistic generalized Polynomial Chaos Expansion (PgPCE)
#     PPCE = gPCE + GPR
###############################################################
#--------------------------------------------------------------
# Saleh Rezaeiravesh, salehr@kth.se
#--------------------------------------------------------------
"""
   >>> Probabilistic generalized Polynomial Chaos Expansion (PgPCE) 
   [IDEA]:
   We have a true unobserved simulator f(q). We would like to estimate statisical moments of f(q) where q are RV allowed to vary over an admissible space with some distribution. For this probem our appraoch is to use gPCE. However, the training outputs generated by f(q) can be uncertain themselves. To handle this we need to combine gPCE and GPR-surrogates. By solving this problem, we make estimations for statistical moments of f(q) which are now random!
   [Required Steps]:
   1. Construct a GPR-surrogate for f(q) (shown by g(q)) based on limited number of noisy training data: y=g(q)+e
      - Through this, the uncertainty in each observation is taken into account in the GPR surrogate.
      - GPR supports both homoscedastic and heteroscedastic noises
      - GPR is built using GPyTorch
   2. Use gPCE to estimate statisical moments of the surrogate (and hence actual f(q)) due to the variablity of the q over an admissible space.     
      - To gPCE is constructed based on Gauss-Quadrature technique. Since it is efficient, considering the low expense of drawing samples from GPR surrogate.
      - As a result of PgPCE, estimates for mean and variance of g(q) are random variables.
        To construct their dstribution, we do brute force MC.
        This means, we repeat m times estimating the gPCE moments based on Gauss quadrature samples taken from the GPR.
   NOTE: now only works for uniform q!     
"""
#
import os
import sys
import numpy as np
import math as mt
import matplotlib
import matplotlib.pyplot as plt
UQit=os.getenv("UQit")
sys.path.append(UQit)
import pce
import gpr_torch
import pdfHisto
import analyticTestFuncs
import writeUQ
import reshaper
import sampling
#
def ppce_1d_cnstrct(qTrain,yTrain,noiseSdev,ppceDict):
    """
       Probabistric PCE (gPCE+GPR) for 1d-input parameter, y=f(q)+e
       Inputs:
           qTrain: training input parameters q, 1d numpy array of size n
           yTrain: training observed output y, 1d numpy array of size n
           noiseSdev: noise sdev of training observations: e~N(0,noiseSdev), 1d numpy array of size n
           ppceDict: dictionary containing controllers for PPCE, including:
                nGQ: number of GQ test points 
                qBound: admissible range of q
                nMC: number of independent samples drawn from GPR to construct PCE 
                nIter_gpr: number of iterations for optimization of GPR hyper-parameters
                lr_gpr: learning rate for optimization of GPT hyper-parameters
       Outputs:
           fMean_list: PCE estimates for the mean of f(q), 1d numpy array
           fVar_list : PCE estimates for the var of f(q) , 1d numpy array
           optOut: optional outputs for plotting
    """
    print('... Probabilistic PCE for 1D input parameter.')
    #(0) assignments
    nGQ=ppceDict['nGQtest']       #number of GQ test points in the parameter space
    qBound=ppceDict['qBound'] #admissible range of the input parameter q
    nMC=ppceDict['nMC']       #number of samples taken from GPR to estimate PCE coefs
    distType=ppceDict['distType']
    #make a dict for gpr
    gprOpts={'nIter':ppceDict['nIter_gpr'],    #number of iterations to optimize hyperparameters of the GPR
             'lr':ppceDict['lr_gpr'],           #learning rate in opimization of hyperparameters of the GPR
             'convPlot':ppceDict['convPlot_gpr']  #plot convergence of optimization of GPR hyperparameters
            }

    #(1) Generate test points that are Gauss quadratures chosen based on the distribution of q (gPCE rule) 
    xiGQ,wGQ=pce.gqPtsWts(nGQ,distType)  
    if distType=='Unif':
       qTest=pce.mapFromUnit(xiGQ,qBound) #qTest\in qBound

    #(2) Construct GPR surrogate based on training data
    post_f,post_obs=gpr_torch.gprTorch_1d(qTrain,[yTrain],noiseSdev,qTest,gprOpts)

    #(3) Use samples of GPR tested at GQ nodes to construct a PCE
    #    nMC independent samples are drawn from the GPR surrogate
    fMean_list=[]      #list of estimates for E[f(q)] 
    fVar_list =[]      #list of estimates for V[f(q)]
    pceDict={'sampleType':'GQ','pceSolveMethod':'Projection','distType':distType}
    for j in range(nMC):
        # draw a sample for f(q) from GPR surrogate
        f_=post_obs.sample().numpy()
        # construct PCE for the drawn sample
        fCoef_,fMean_,fVar_=pce.pce_1d_cnstrct(f_,[],pceDict)
        fMean_list.append(fMean_)
        fVar_list.append(fVar_)
        if ((j+1)%50==0):
           print("...... ppce repetition for finding samples of the PCE coefficients, iter = %d/%d" %(j,nMC))

    #(4) Convert lists to numpy arrays    
    # estimates for their mean and sdev: fMean_list.mean(), fMean_list.std(), ...
    fMean_list=np.asarray(fMean_list)
    fVar_list=np.asarray(fVar_list)
    #optional outputs: only used for plot in the test below
    #in general we do not need them
    optOut={'post_f':post_f,'post_obs':post_obs,'qTest':qTest}
    return fMean_list,fVar_list,optOut
#
def ppce_pd_cnstrct(qTrain,yTrain,noiseSdev,ppceDict):
    """
       Probabistric PCE (gPCE+GPR) for pd-input parameter, y=f(q)+e
       Inputs:
           qTrain: training input parameters q, pd numpy array of size nxp
           yTrain: training observed output y, 1d numpy array of size n
           noiseSdev: noise sdev of training observations: e~N(0,noiseSdev), 1d numpy array of size n
           ppceDict: dictionary containing controllers for PPCE, including:
                nGQ: list of number of GQ test points in each direction 
                qBound: admissible range of q, list of length p
                nMC: number of independent samples drawn from GPR to construct PCE 
                nIter_gpr: number of iterations for optimization of GPR hyper-parameters
                lr_gpr: learning rate for optimization of GPT hyper-parameters
       Outputs:
           fMean_list: PCE estimates for the mean of f(q), 1d numpy array
           fVar_list : PCE estimates for the var of f(q) , 1d numpy array
           optOut: optional outputs for plotting
    """
    print('... Probabilistic PCE for 2D input parameter.')
    #(0) Assignments
    p=qTrain.shape[-1]    #dimension of input parameter q
    nGQ=ppceDict['nGQtest']       #list of number of GQ test points in each of p dimensions of the parameter q
    qBound=ppceDict['qBound']     #admissible range of inputs parameter
    nMC=ppceDict['nMC']           #number of samples taken from GPR for estimating PCE coefs
    distType=ppceDict['distType']
    #make a dict for gpr (do NOT change)
    gprOpts={'nIter':ppceDict['nIter_gpr'],    #number of iterations to optimize hyperparameters of GPR
             'lr':ppceDict['lr_gpr'],          #learning rate in opimization of hyperparameters of GPR
             'convPlot':ppceDict['convPlot_gpr']  #plot convergence of optimization of GPR hyperparameters
            }
    #make a dict for PCE (do NOT change)
    pceDict={'truncMethod':'TP',  #always use TP truncation with GQ sampling with Projection (GQ rule)
             'sampleType':'GQ', 
             'pceSolveMethod':'Projection',
             'distType':distType
             }

    #(1) Generate test points that are Gauss quadratures chosen based on the distribution of q (gPCE rule) 
    qTestGrid=[]
    for i in range(p):
        xiGQ_,wGQ_=pce.gqPtsWts(nGQ[i],distType[i]) 
        if distType[i]=='Unif':
           qTestGrid.append(pce.mapFromUnit(xiGQ_,qBound[i])) #qTest\in qBound
    qTest=reshaper.vecs2grid(qTestGrid)

    #(2) Construct GPR surrogate based on training data
    post_f,post_obs=gpr_torch.gprTorch_pd(qTrain,[yTrain],noiseSdev,qTest,gprOpts)

    #(3) Use samples of GPR tested at GQ nodes to construct a PCE
    #    nMC independent samples are drawn from the GPR surrogate
    fMean_list=[]      #list of estimates for E[f(q)] 
    fVar_list =[]      #list of estimates for V[f(q)]
    for j in range(nMC):
        # draw a sample for f(q) from GPR surrogate
        f_=post_obs.sample().numpy()
        # construct PCE for the drawn sample
        fCoef_,kSet_,fMean_,fVar_=pce.pce_pd_cnstrct(f_,nGQ,[],pceDict)
        fMean_list.append(fMean_)
        fVar_list.append(fVar_)
        if ((j+1)%50==0):
           print("...... ppce repetition for finding samples of the PCE coefficients, iter = %d/%d" %(j,nMC))

    #(4) Convert lists to numpy arrays    
    # estimates for their mean and sdev: fMean_list.mean(), fMean_list.std(), ...
    fMean_list=np.asarray(fMean_list)
    fVar_list=np.asarray(fVar_list)
    #optional outputs: only used for plot in the test below
    #in general we do not need them
    optOut={'post_f':post_f,'post_obs':post_obs,'qTest':qTest,'qTestGrid':qTestGrid}
    return fMean_list,fVar_list,optOut
#
#
###############################
# Tests
###############################
import torch   #for plot
def ppce_1d_test():
    """
        Test PPCE over 1D parameter space
    """
    def fEx(x):
        """
           Exact simulator
        """
        #yEx=np.sin(2*mt.pi*x)
        yEx=analyticTestFuncs.fEx1D(x,fType)
        return yEx
    #
    def noiseGen(n,noiseType):
        """
           Generate a 1D numpy array of standard deviations of independent Gaussian noises
        """
        if noiseType=='homo': #homoscedastic noise 
           sd=0.1   #standard deviation (NOTE: cannot be zero, but can be very small)
           sdV=[sd]*n
           sdV=np.asarray(sdV)
        elif noiseType=='hetero': #heteroscedastic noise
           sdMin=0.02
           sdMax=0.2
           sdV=sdMin+(sdMax-sdMin)*np.linspace(0.0,1.0,n)
        return sdV  #vector of standard deviations
    #
    def trainData(xBound,n,noiseType):
        """
          Create training data D={X,Y}
        """
        x=np.linspace(xBound[0],xBound[1],n)
        sdV=noiseGen(n,noiseType)
        y=fEx(x) + sdV * np.random.randn(n)
        return x,y,sdV
    #
    def gpr1D_plotter(post_f,post_obs,xTrain,yTrain,xTest,fExTest):
        """
           Plot GPR constructed by GPyToch for 1D input
        """
        with torch.no_grad():
             lower_f, upper_f = post_f.confidence_region()
             lower_obs, upper_obs = post_obs.confidence_region()
             plt.figure(figsize=(10,6))
             plt.plot(xTest,fExTest,'--b',label='Exact Output')
             plt.plot(xTrain, yTrain, 'ok',markersize=4,label='Training observations')
             plt.plot(xTest, post_f.mean[:].numpy(), '-r',lw=2,label='Mean Model')
             plt.plot(xTest, post_obs.mean[:].numpy(), ':m',lw=2,label='Mean Posterior Prediction')
             plt.plot(xTest, post_obs.sample().numpy(), '-k',lw=1,label='Sample Posterior Prediction')
             plt.fill_between(xTest, lower_f.numpy(), upper_f.numpy(), alpha=0.3,label='Confidence f(q)')
             plt.fill_between(xTest, lower_obs.numpy(), upper_obs.numpy(), alpha=0.15, color='r',label='Confidence Yobs')
             plt.legend(loc='best',fontsize=15)
             #NOTE: confidence = 2* sdev, 
             plt.title('Single-Task GP + Heteroscedastic Noise')
             plt.xticks(fontsize=18)
             plt.yticks(fontsize=18)
             plt.xlabel(r'$\mathbf{q}$',fontsize=17)
             plt.ylabel(r'$y$',fontsize=17)
             plt.show()
    #
    #
    #-------SETTINGS------------------------------
    n=12       #number of training data
    nGQtest=50   #number of test points (=Gauss Quadrature points)
    qBound=[0,1]   #range of input
    #type of the noise in the data
    noiseType='hetero'   #'homo'=homoscedastic, 'hetero'=heterscedastic
    distType='Unif'
    #GPR options
    nIter_gpr=800      #number of iterations in optimization of hyperparameters
    lr_gpr   =0.1      #learning rate for the optimizaer of the hyperparameters    
    convPlot_gpr=True  #plot convergence of optimization of GPR hyperparameters
    #number of samples drawn from GPR surrogate to construct estimates for moments of f(q)
    nMC=1000
    #---------------------------------------------    
    if distType=='Unif':
       fType='type1' 
    #(1) Generate synthetic training data
    qTrain,yTrain,noiseSdev=trainData(qBound,n,noiseType)
    #(2) Probabilistic gPCE 
    #   (a) make the dictionary
    ppceDict={'nGQtest':nGQtest,'qBound':qBound,'distType':distType,'nIter_gpr':nIter_gpr,'lr_gpr':lr_gpr,'convPlot_gpr':convPlot_gpr,'nMC':nMC}
    #   (b) call the method
    fMean_samples,fVar_samples,optOut=ppce_1d_cnstrct(qTrain,yTrain,noiseSdev,ppceDict)
    #(3) postprocess
    #   (a) plot the GPR surrogate along with response from the exact simulator    
    gpr1D_plotter(optOut['post_f'],optOut['post_obs'],qTrain,yTrain,optOut['qTest'],fEx(optOut['qTest']))
    #   (b) plot histogram and pdf of the mean and variance distribution 
    pdfHisto.pdfFit_uniVar(fMean_samples,True,[])
    pdfHisto.pdfFit_uniVar(fVar_samples,True,[])
    #   (c) compare the exact moments with estimated values by ppce
    fMean_ex,fVar_ex=analyticTestFuncs.fEx1D_moments(qBound,fType)
    fMean_mean=fMean_samples.mean()
    fMean_sdev=fMean_samples.std()
    fVar_mean=fVar_samples.mean()
    fVar_sdev=fVar_samples.std()
    print(writeUQ.printRepeated('-', 80))
    print('>> Exact mean(f) = %g' %fMean_ex)
    print('   ppce estimated: E[mean(f)] = %g , sdev[mean(f)] = %g' %(fMean_mean,fMean_sdev))
    print('>> Exact Var(f) = %g' %fVar_ex)
    print('   ppce estimated: E[Var(f)] = %g , sdev[Var(f)] = %g' %(fVar_mean,fVar_sdev))
#	
#//////////////////////////////////
def ppce_2d_test():
    """
        Test for ppce_pd_cnstrct()
        Note: some functions are taken from /gpr_torch.py/gprTorch_2d_singleTask_test()
    """
    ##
    def trainDataGen(p,sampleType,n,qBound,fExName,noiseType):
        """
           Generate Training Data
        """
        #  (a) xTrain
        if sampleType=='grid':
          nSamp=n[0]*n[1]
          gridList=[];
          for i in range(p):
              grid_=np.linspace(qBound[i][0],qBound[i][1],n[i])
              gridList.append(grid_)
          xTrain=reshaper.vecs2grid(gridList)
        elif sampleType=='random':
             nSamp=n
             xTrain=sampling.LHS_sampling(nSamp,qBound)
        #  (b) set the sdev of the observation noise
        noiseSdev=noiseGen(nSamp,noiseType,xTrain,fExName)
        #  (c) Training data
        yTrain=analyticTestFuncs.fEx2D(xTrain[:,0],xTrain[:,1],fExName,'pair')
        yTrain_noiseFree=yTrain
        yTrain=yTrain_noiseFree+noiseSdev*np.random.randn(nSamp)
        return xTrain,yTrain,noiseSdev,yTrain_noiseFree
    ##
    def noiseGen(n,noiseType,xTrain,fExName):
       """
          Generate a 1D numpy array of standard deviations of independent Gaussian noises
       """
       if noiseType=='homo':
          sd=0.2   #standard deviation (NOTE: cannot be zero)
          sdV=sd*np.ones(n)
       elif noiseType=='hetero':
          sdV=0.1*(analyticTestFuncs.fEx2D(xTrain[:,0],xTrain[:,1],fExName,'pair')+0.001)
       return sdV  #vector of standard deviations
    ##
    def gpr_torch_postProc(post_,nTest):
        """
           Convert the outputs of gpr-torch to numpy format suitable for contourplot
        """
        with torch.no_grad():
            post_mean_=post_.mean.detach().numpy()
            post_mean =post_mean_.reshape((nTest[0],nTest[1]),order='F')   #posterior mean
            lower_, upper_ = post_.confidence_region()     #\pm 2*sdev of posterior mean
            lower_=lower_.detach().numpy().reshape((nTest[0],nTest[1]),order='F')
            upper_=upper_.detach().numpy().reshape((nTest[0],nTest[1]),order='F')
            post_sdev = (post_mean-lower_)/2.0   #sdev of the posterior mean of f(q)
        return post_mean,post_sdev,lower_,upper_
    ##
    def gpr_3dsurf_plot(xTrain,yTrain,testGrid,nTest,post_obs,post_f):
        """
           3D plot of the GPR surface (mean+CI)
        """
        #Predicted mean and variance at the test grid
        post_f_mean,post_f_sdev,lower_f,upper_f=gpr_torch_postProc(post_f,nTest)
        post_obs_mean,post_obs_sdev,lower_obs,upper_obs=gpr_torch_postProc(post_obs,nTest)

        xTestGrid1,xTestGrid2=np.meshgrid(testGrid[0],testGrid[1], sparse=False, indexing='ij')
        fig = plt.figure()
        ax = fig.gca(projection='3d')
        mean_surf = ax.plot_surface(xTestGrid1, xTestGrid2, post_obs_mean,cmap='jet', antialiased=True,rstride=1,cstride=1,linewidth=0,alpha=0.4)
        upper_surf_obs = ax.plot_wireframe(xTestGrid1, xTestGrid2, upper_obs, linewidth=1,alpha=0.25,color='r')
        lower_surf_obs = ax.plot_wireframe(xTestGrid1, xTestGrid2, lower_obs, linewidth=1,alpha=0.25,color='b')
        #upper_surf_f = ax.plot_wireframe(xTestGrid1, xTestGrid2, upper_f, linewidth=1,alpha=0.5,color='r')
        #lower_surf_f = ax.plot_wireframe(xTestGrid1, xTestGrid2, lower_f, linewidth=1,alpha=0.5,color='b')
        plt.plot(xTrain[:,0],xTrain[:,1],yTrain,'ok')
        plt.show()
    ##
    #
    #----- SETTINGS -------------------------------------------
    qBound=[[-2,2],[-2,2]]   #Admissible range of parameters
    distType=['Unif','Unif']
    #options for training data
    fExName='type2'          #Name of Exact function to generate synthetic data
                             #This is typ in fEx2D() in ../../analyticFuncs/analyticFuncs.py
    trainSampleType='random'        #'random' or 'grid': type of samples
    if trainSampleType=='grid':
       n=[10,10]               #number of training observations in each input dimension
    elif trainSampleType=='random':
       n=100               #total number of training samples drawn randomly
    #NOTE: there might be limitation for n*nGQtest because of torch, since we are not using batch   
    noiseType='homo'       #'homo'=homoscedastic, 'hetero'=heterscedastic
    #options for GPR
    nIter_gpr=1000      #number of iterations in optimization of hyperparameters
    lr_gpr   =0.1      #learning rate for the optimizaer of the hyperparameters
    convPlot_gpr=True  #plot convergence of optimization of GPR hyperparameters
    #options for Gauss Quadrature test points
    nGQtest=[18,18]     #number of test points in each param dimension
    #number of samples drawn from GPR surrogate to construct estimates for moments of f(q)
    nMC=200
    #---------------------------------------------------------
    p=len(distType)  #dimension of the input parameter q
    #(1) Generate synthetic training data
    qTrain,yTrain,noiseSdev,yTrain_noiseFree=trainDataGen(p,trainSampleType,n,qBound,fExName,noiseType)
    #(2) Probabilistic gPCE 
    #   (a) make the dictionary
    ppceDict={'nGQtest':nGQtest,'qBound':qBound,'distType':distType,'nIter_gpr':nIter_gpr,'lr_gpr':lr_gpr,'convPlot_gpr':convPlot_gpr,'nMC':nMC}
    #   (b) call the method
    fMean_samples,fVar_samples,optOut=ppce_pd_cnstrct(qTrain,yTrain,noiseSdev,ppceDict)
    #(3) postprocess
    #   (a) plot the GPR surrogate along with response from the exact simulator    
    gpr_3dsurf_plot(qTrain,yTrain,optOut['qTestGrid'],nGQtest,optOut['post_obs'],optOut['post_f'])
    #   (b) plot histogram and pdf of the mean and variance distribution 
    pdfHisto.pdfFit_uniVar(fMean_samples,True,[])
    pdfHisto.pdfFit_uniVar(fVar_samples,True,[])
    #   (c) compare the exact moments with estimated values by ppce
    #fMean_ex,fVar_ex=analyticTestFuncs.fEx1D_moments(qBound)
    fMean_mean=fMean_samples.mean()
    fMean_sdev=fMean_samples.std()
    fVar_mean=fVar_samples.mean()
    fVar_sdev=fVar_samples.std()
    print(writeUQ.printRepeated('-', 80))
    #print('>> Exact mean(f) = %g' %fMean_ex)
    print('   ppce estimated: E[mean(f)] = %g , sdev[mean(f)] = %g' %(fMean_mean,fMean_sdev))
    #print('>> Exact Var(f) = %g' %fVar_ex)
    print('   ppce estimated: E[Var(f)] = %g , sdev[Var(f)] = %g' %(fVar_mean,fVar_sdev))


