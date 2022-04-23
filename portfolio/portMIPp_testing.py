import pandas as pd
import numpy as np
import numpy.linalg as npl
import numpy.random as npr
import scipy.linalg as la
from sklearn.model_selection import train_test_split
from sklearn.cluster import KMeans
import cvxpy as cp
import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path  
import sys
output_stream = sys.stdout
import gurobipy as gp
from gurobipy import GRB
import time
import mosek
import os
from joblib import Parallel, delayed

def cluster_data(D_in, K):
    '''returns K cluster means after clustering D_in into K clusters'''
    N = D_in.shape[0]
    kmeans = KMeans(n_clusters=K).fit(D_in)
    Dbar_in = kmeans.cluster_centers_
    weights = np.bincount(kmeans.labels_) / N
    
    return Dbar_in, weights

def createproblem_portMIP(N, m):
    """Creates the problem in cvxpy"""
    # PARAMETERS #
    dat = cp.Parameter((N, m))
    eps = cp.Parameter()
    w = cp.Parameter(N)
    a = -50
    b = -40

    # VARIABLES #
    # weights, s_i, lambda, tau
    x = cp.Variable(m)
    s = cp.Variable(N)
    lam = cp.Variable()
    z = cp.Variable(m,boolean = True)
    tao = cp.Variable()
    t = cp.Variable()
    # OBJECTIVE #
    objective = t

    # CONSTRAINTS #
    constraints = [cp.multiply(eps, lam) + w@s <= t]
    constraints += [10*tao <= t]
    constraints += [cp.hstack([b*tao]*N) + a*dat@x + cp.hstack([cp.quad_over_lin(-a*x, 4*lam)]*N) <= s]
    constraints += [cp.sum(x) == 1]
    constraints += [x >= 0, x <= 1]
    #for k in range(2):
    #    constraints += [cp.sum(x[k*np.ceil(m/2):(k+1)*np.ceil(m/2)]) <= 0.50]
    constraints += [lam >= 0]
    constraints += [x - z <= 0, cp.sum(z)<=5]
    # PROBLEM #
    problem = cp.Problem(cp.Minimize(objective), constraints)
    return problem, x, s, tao, lam, dat, eps, w

def port_experiment(dat, dateval, r, m, prob, N_tot, K_tot,K_nums, eps_tot, eps_nums):
    x_sols = np.zeros((K_tot, eps_tot, m))
    Opt_vals = np.zeros((K_tot,eps_tot))
    eval_vals = np.zeros((K_tot,eps_tot))
    probs = np.zeros((K_tot,eps_tot))
    setuptimes = np.zeros((K_tot))
    solvetimes = np.zeros((K_tot,eps_tot))
    Data = dat
    Data_eval = dateval

   ######################## solve for various K ########################
    for K_count, K in enumerate(K_nums):
        
        #output_stream.write('Percent Complete %.2f%s\r' % ((K_count)/K_tot*100,'%'))
        # output_stream.flush()
        
        print(r,K)
        tnow = time.time()
        d_train, wk = cluster_data(Data[(N_tot*r):(N_tot*(r+1))], K)
        d_eval = Data_eval[(N_tot*r):(N_tot*(r+1))]
        assert(d_train.shape == (K,m))
        problem, x, s, tao, lmbda, data_train_pm,eps_pm, w_pm = prob(K,m)
        data_train_pm.value = d_train
        w_pm.value = wk
        setuptimes[K_count,r] = time.time() - tnow

        ######################## solve for various epsilons ########################
        for eps_count, eps in enumerate(eps_nums):
            eps_pm.value = eps
            problem.solve(ignore_dpp = True, solver = cp.MOSEK, verbose = True,mosek_params = {mosek.dparam.optimizer_max_time:  600.0})
            solvetimes[K_count,eps_count,r] = problem.solver_stats.solve_time
            x_sols[K_count, eps_count, :, r] = x.value
            evalvalue = -np.mean(Data_eval@x.value) -40*tao.value
            eval_vals[K_count, eps_count, r] = evalvalue
            probs[K_count, eps_count, r] = evalvalue <= problem.objective.value 
            print(eps,K, problem.solver_stats.solve_time, problem.objective.value,evalvalue, evalvalue <= problem.objective.value)

            Opt_vals[K_count,eps_count,r] = problem.objective.value

            np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/x.npy"),x_sols)
            np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/Opt_vals.npy"),Opt_vals)
            np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/solvetimes.npy"),solvetimes)
            np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/setuptimes.npy"),setuptimes)
            np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/probs.npy"),probs)
            np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/eval_vals.npy"),eval_vals)

    #, mosek_params = {mosek.dparam.optimizer_max_time:  300.0, mosek.iparam.intpnt_solve_form:   mosek.solveform.dual}
    plt.figure(figsize=(10, 6))
    for K_count, K in enumerate(K_nums):
        plt.plot(eps_nums, np.mean(probs[:,:,:r+1],axis = 2)[K_count,:],linestyle='-', marker='o', color = colors[K_count], label = "$K = {}$".format(round(K,4)))
        plt.xlabel("$\epsilon^2$")
    plt.xscale("log")
    plt.ylabel("Reliability")
    plt.legend()
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/reliability.png')

    plt.figure(figsize=(10, 6))
    for K_count, K in enumerate(K_nums):
        plt.plot(eps_nums, np.mean(Opt_vals[:,:,:r+1],axis = 2)[K_count,:],linestyle='-', marker='o', color = colors[K_count], label = "$K = {}$".format(round(K,4)))
        plt.xlabel("$\epsilon^2$")
    plt.xscale("log")
    plt.ylabel("Optimal value")
    plt.legend()
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/objs.png')

    plt.figure(figsize=(10, 6))

    for eps_count, eps in enumerate(eps_nums):
        plt.plot(K_nums,np.mean(solvetimes[:,:,:r+1],axis = 2)[:,eps_count],linestyle='-', marker='o', label = "$\epsilon^2 = {}$".format(round(eps,6)), alpha = 0.5)
        plt.xlabel("Number of clusters (K)")

    plt.ylabel("time")
    plt.title("Solve time")
    plt.legend()
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/solvetime.png')


    plt.figure(figsize=(10, 6))
    plt.plot(K_nums, np.mean(setuptimes[:,:r+1],axis = 1),linestyle='-', marker='o')
    plt.xlabel("Number of clusters (K)")
    plt.ylabel("time")
    plt.title("Set-up time (clustering + creating problem)")
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/setuptime.png')

    for eps_count, eps in enumerate(eps_nums):
        plt.plot(K_nums,np.mean(setuptimes[:,:r+1],axis = 1) + np.mean(solvetimes[:,:,:r+1],axis = 2)[:,eps_count],linestyle='-', marker='o', label = "$\epsilon^2 = {}$".format(round(eps,6)), alpha = 0.5)
        plt.xlabel("Number of clusters (K)")

    plt.ylabel("time")
    plt.title("totaltime")
    plt.legend()
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/totaltime.png')

    #output_stream.write('Percent Complete %.2f%s\r' % (100,'%'))  
    
    return x_sols, Opt_vals, eval_vals, probs,setuptimes,solvetimes


#mosek_params = {mosek.dparam.optimizer_max_time:  300.0, mosek.iparam.intpnt_solve_form:   mosek.solveform.dual}
    
colors = ["tab:blue", "tab:orange", "tab:green",
        "tab:red", "tab:purple", "tab:brown", "tab:pink", "tab:grey", "tab:olive","tab:blue", "tab:orange", "tab:green",
        "tab:red", "tab:purple", "tab:brown", "tab:pink", "tab:grey", "tab:olive"]


if __name__ == '__main__':
    synthetic_returns = pd.read_csv('/scratch/gpfs/iywang/mro_code/portfolio/sp500_synthetic_returns.csv').to_numpy()[:,1:]

    K_nums = np.array([1,5,50,100,300])
    #np.array([1,10,20,50,100,500,1000]) # different cluster values we consider
    K_tot = K_nums.size  # Total number of clusters we consider
    N_tot = 300
    M = 10
    R = 5           # Total times we repeat experiment to estimate final probabilty
    m = 30 
    eps_min = -5    # minimum epsilon we consider
    eps_max = -3.9       # maximum epsilon we consider
    eps_nums = np.linspace(eps_min,eps_max,M)
    eps_nums = 10**(eps_nums)
    eps_tot = M

    dat = synthetic_returns[:10000,:m]
    dateval = synthetic_returns[-10000:,:m]

    results = Parallel(n_jobs=2)(port_experiment(dat,dateval,r, m, createproblem_portMIP,N_tot, K_tot,K_nums, eps_tot,eps_nums) for r in range(R))

    x_sols, Opt_vals, eval_vals, probs,setuptimes,solvetimes = port_experiment(dat,dateval,R, m, createproblem_portMIP,N_tot, K_tot,K_nums, eps_tot,eps_nums)

    np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/x.npy"),x_sols)
    np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/Opt_vals.npy"),Opt_vals)
    np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/solvetimes.npy"),solvetimes)

    np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/setuptimes.npy"),setuptimes)
    np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/probs.npy"),probs)
    np.save(Path("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/eval_vals.npy"),eval_vals)

    plt.figure(figsize=(10, 6))
    for K_count, K in enumerate(K_nums):
        plt.plot(eps_nums, np.mean(Opt_vals[:,:,],axis = 2)[K_count,:],linestyle='-', marker='o', color = colors[K_count], label = "$K = {}$".format(round(K,4)))
        plt.xlabel("$\epsilon^2$")
    plt.xscale("log")
    plt.ylabel("Optimal value")
    plt.legend()
    plt.show()
    plt.savefig("/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/objs.png")

    plt.figure(figsize=(10, 6))
    for K_count, K in enumerate(K_nums):
        plt.plot(eps_nums, np.mean(probs[:,:,],axis = 2)[K_count,:],linestyle='-', marker='o', color = colors[K_count], label = "$K = {}$".format(round(K,4)))
        plt.xlabel("$\epsilon^2$")
    plt.xscale("log")
    plt.ylabel("Reliability")
    plt.legend()
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/reliability.png')

    plt.figure(figsize=(10, 6))
    for eps_count, eps in enumerate(eps_nums):
        plt.plot(K_nums,np.mean(solvetimes[:,:,],axis = 2)[:,eps_count],linestyle='-', marker='o', label = "$\epsilon^2 = {}$".format(round(eps,6)), alpha = 0.5)
        plt.xlabel("Number of clusters (K)")

    plt.ylabel("time")
    plt.title("Solve time")
    plt.legend()
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/solvetime.png')

    plt.figure(figsize=(10, 6))
    plt.plot(K_nums,np.mean(setuptimes,axis = 1),linestyle='-', marker='o')
    plt.xlabel("Number of clusters (K)")
    plt.ylabel("time")
    plt.title("Set-up time (clustering + creating problem)")
    plt.show()

    plt.figure(figsize=(10, 6))
    for eps_count, eps in enumerate(eps_nums):
        plt.plot(K_nums,np.mean(setuptimes,axis = 1) + np.mean(solvetimes[:,:,],axis = 2)[:,eps_count],linestyle='-', marker='o', label = "$\epsilon^2 = {}$".format(round(eps,6)), alpha = 0.5)
        plt.xlabel("Number of clusters (K)")

    plt.ylabel("time")
    plt.title("Total time")
    plt.legend(fontsize=5)
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/portfolio/MIP/m=100,K=500,r=5/totaltime.png')

    print("COMPLETE")