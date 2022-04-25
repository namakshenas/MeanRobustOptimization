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
import sys
import time
output_stream = sys.stdout
import gurobipy as gp
from gurobipy import GRB
import time
colors = ["tab:blue", "tab:orange", "tab:green",
          "tab:red", "tab:purple", "tab:brown", "tab:pink", "tab:grey", "tab:olive","tab:blue", "tab:orange", "tab:green",
          "tab:red", "tab:purple", "tab:brown", "tab:pink", "tab:grey", "tab:olive"]

from pathlib import Path  
import mosek
import os
from joblib import Parallel, delayed

def get_n_processes(max_n=np.inf):
    """Get number of processes from current cps number
    Parameters
    ----------
    max_n: int
        Maximum number of processes.
    Returns
    -------
    float
        Number of processes to use.
    """

    try:
        # Check number of cpus if we are on a SLURM server
        n_cpus = int(os.environ["SLURM_CPUS_PER_TASK"])
    except KeyError:
        n_cpus = joblib.cpu_count()

    n_proc = max(min(max_n, n_cpus), 1)

    return n_proc

def cluster_data(D_in, K):
    '''returns K cluster means after clustering D_in into K clusters'''
    N = D_in.shape[0]
    kmeans = KMeans(n_clusters=K).fit(D_in)
    Dbar_in = kmeans.cluster_centers_
    weights = np.bincount(kmeans.labels_) / N
    
    return Dbar_in, weights

def prob_facility_kuhn(K,m,n):
    
    eps = cp.Parameter()
    d_train = cp.Parameter((K,m))
    wk = cp.Parameter(K)
    p = cp.Parameter(n)
    c = cp.Parameter(n)
    C = cp.Parameter((n,m))
    minnum = cp.Parameter()
    x = cp.Variable(n, boolean = True)
    X = cp.Variable((n,m))
    lmbda = cp.Variable()
    s = cp.Variable(K)
    t = cp.Variable()
    z = cp.Variable(n,boolean = True)
    objective = cp.Minimize(cp.trace(C.T @ X) + c@x)
    #cp.Minimize(t)

    constraints = [cp.multiply(eps,lmbda) + wk @ s <= 0]
    for j in range(m):
        constraints += [cp.sum(X[:, j]) == 1]  
    for i in range(n):
        constraints += [cp.hstack([-minnum + (-p[i]+ minnum)*x[i]]*K) + d_train @
                        X[i] + cp.hstack([cp.quad_over_lin(X[i], 4*lmbda)]*K) <= s]
            
    constraints += [X >= 0, lmbda >= 0]
    constraints += [cp.sum(X,axis = 1 )/m - z <= 0, x >= z]
    problem = cp.Problem(objective,constraints)
    
    return problem, x, X, s, lmbda, d_train, wk, eps, p, c, C

def prob_facility_separate(K,m,n):
    
    eps = cp.Parameter()
    d_train = cp.Parameter((K,m))
    wk = cp.Parameter(K)
    p = cp.Parameter(n)
    c = cp.Parameter(n)
    C = cp.Parameter((n,m))

    x = cp.Variable(n, boolean = True)
    X = cp.Variable((n,m))
    lmbda = cp.Variable(n)
    #s = cp.Variable(K)
    s = cp.Variable((n,K))
    t = cp.Variable()

    objective = cp.Minimize(cp.trace(C.T @ X) + c@x)
    #cp.Minimize(t)

    constraints = []
    for j in range(m):
        constraints += [cp.sum(X[:, j]) == 1]
    for i in range(n):
        constraints += [cp.multiply(eps,lmbda[i]) + wk @ s[i] <= 0]
        constraints += [cp.hstack([-p[i]*x[i]]*K) + d_train@X[i] +
                        cp.hstack([cp.quad_over_lin(X[i], 4*lmbda[i])]*K) <= s[i]]
    constraints += [X >= 0, lmbda >= 0]

    problem = cp.Problem(objective,constraints)
    
    return problem, x, X, s, lmbda, d_train, wk, eps, p, c, C


def generate_facility_data(num_facilities = 10, num_locations = 50, K = 100):
    '''data for one problem instance of facility problem'''
    n = num_facilities
    m = num_locations
    
    # Cost for facility
    c = npr.randint(30,70,n)
    
    # Cost for shipment
    fac_loc = npr.randint(0,15,size= (n,2))
    cus_loc = npr.randint(0,15,size= (m,2))
    rho = 4
    
    C = np.zeros((n,m))
    for i in range(n):
        for j in range(m):
            C[i,j] = npl.norm(fac_loc[i,:] - cus_loc[j,:])
            
    # Capacities for each facility
    p = npr.randint(10,50,n)
    
    # Past demands of customer (past uncertain data)
    return c,C,p
    
def generate_facility_demands(N_tot, m, R_samples = 30):
    d_train = npr.randint(1,5,(N_tot, m, R_samples))
    return d_train

def evaluate(p, x, X, d):
    for ind in range(n):
        #print(-p.value[ind]*x.value[ind] + np.reshape(np.mean(d,
         #    axis=0), (1, m))@(X.value.T@(np.eye(n)[ind])))
        if -p.value[ind]*x.value[ind] + np.reshape(np.mean(d, axis=0), (1, m))@(X.value[ind]) >= 0.001:
            return 0
    return 1

def evaluate_k(p, x, X, d):
    maxval = np.zeros((np.shape(d)[0],np.shape(x)[0]))
    for fac in range(np.shape(x)[0]):
        for ind in range(np.shape(d)[0]):
            maxval[ind,fac] = -p.value[fac]*x.value[fac]+ d[ind]@X.value[fac]
            #if x.value[fac] >0:
            #    print(-p.value[fac]+ d[ind]@X.value[fac])
            #*x.value[fac] 
    #print(maxval)
    #print(np.max(maxval,axis = 1))
    print(np.mean(np.max(maxval,axis = 1)))
    if np.mean(np.max(maxval,axis = 1)) >= 0.001:
        return 0
    return 1

def facility_experiment(r, n,m, Data, Data_eval, prob_facility, N_tot, K_tot,K_nums, eps_tot , eps_nums, foldername):
    X_sols = np.zeros((K_tot, eps_tot, n,m, R)) 
    x_sols = np.zeros((K_tot, eps_tot, n, R))
    Opt_vals = np.zeros((K_tot,eps_tot, R))
    eval_vals = np.zeros((K_tot,eps_tot, R))
    eval_vals1 = np.zeros((K_tot,eps_tot, R))
    clustertimes = np.zeros((K_tot,R))
    setuptimes = np.zeros((K_tot,R))
    solvetimes = np.zeros((K_tot,eps_tot,R))

    ######################## Repeat experiment R times ########################
        ######################## solve for various K ########################
    for K_count, K in enumerate(K_nums):
        
        #output_stream.write('Percent Complete %.2f%s\r' % ((K_count)/K_tot*100,'%'))
        #output_stream.flush()
        if K == N_tot:
            d_train = Data[:,:,r]
            wk = np.ones(K)*(1/K)
            clustertimes[K_count,r] = 0
        else:
            tnow = time.time()
            d_train, wk = cluster_data(Data[:,:,r], K)
            clustertimes[K_count,r] = time.time() - tnow
        
        dat_eval = Data_eval[:,:,r]
        tnow = time.time()
        problem, x, X, s, lmbda, data_train_pm, w_pm, eps_pm, p_pm, c_pm, C_pm = prob_facility(K,m,n)
        data_train_pm.value = d_train
        w_pm.value = wk
        p_pm.value = p
        c_pm.value = c
        C_pm.value = C

        setuptimes[K_count,r] = time.time() - tnow

        ######################## solve for various epsilons ########################
        for eps_count, eps in enumerate(eps_nums):
            tnow1 = time.time()
            eps_pm.value = eps
            problem.solve(ignore_dpp = True, solver = cp.MOSEK, verbose = True,mosek_params = {mosek.dparam.optimizer_max_time:  1000.0})
            #print(eps,K, problem.objective.value)
            solvetimes[K_count,eps_count,r] = problem.solver_stats.solve_time
            #time.time() - tnow1
            X_sols[K_count, eps_count, :, :, r] = X.value
            x_sols[K_count, eps_count, :, r] = x.value
            evalvalue = evaluate(p_pm,x,X,dat_eval)
            evalvalue1 = evaluate_k(p_pm,x,X,dat_eval)
            print(K, eps, problem.solver_stats.solve_time, problem.objective.value, evalvalue)
            eval_vals[K_count, eps_count, r] = evalvalue
            eval_vals1[K_count, eps_count, r] = evalvalue1
            Opt_vals[K_count,eps_count,r] = problem.value                         

    #output_stream.write('Percent Complete %.2f%s\r' % (100,'%'))  
    
    return X_sols, x_sols, Opt_vals, eval_vals, eval_vals1, setuptimes, solvetimes, clustertimes

if __name__ == '__main__':
    foldername = "facility/m50n10_K100_r10"
    K_nums = np.array([1,10,50,100]) # different cluster values we consider
    K_tot = K_nums.size  # Total number of clusters we consider
    N_tot = 100
    M = 10
    R = 10       # Total times we repeat experiment to estimate final probabilty
    n = 10 # number of facilities
    m = 50 # number of locations
    eps_min = 1      # minimum epsilon we consider
    eps_max = 25         # maximum epsilon we consider
    eps_nums = np.linspace(eps_min,eps_max,M)
    eps_tot = M 
    c,C,p = generate_facility_data(n,m,R)
    Data = generate_facility_demands(N_tot,m, R_samples = R)
    Data_eval = generate_facility_demands(N_tot, m,R_samples = R)

    njobs = get_n_processes(25)

    results = Parallel(n_jobs=njobs)(delayed(facility_experiment)(r,n,m,Data,Data_eval,prob_facility_separate,N_tot, K_tot,K_nums, eps_tot , eps_nums,foldername) for r in range(R))

    X_sols = np.zeros((K_tot, eps_tot, n,m, R)) 
    x_sols = np.zeros((K_tot, eps_tot, n, R))
    Opt_vals = np.zeros((K_tot,eps_tot, R))
    probs = np.zeros((K_tot,eps_tot, R))
    probs1 = np.zeros((K_tot,eps_tot, R))
    setuptimes = np.zeros((K_tot,R))
    solvetimes = np.zeros((K_tot,eps_tot,R))
    clustertimes = np.zeros((K_tot,R))

    for r in range(R):
        X_sols += results[r][0]
        x_sols += results[r][1]
        Opt_vals += results[r][2]
        probs += results[r][3]
        probs1 += results[r][4]
        setuptimes += results[r][5]
        solvetimes += results[r][6]
        clustertimes +=  results[r][7]

    np.save(Path("/scratch/gpfs/iywang/mro_results/" + foldername + "/x_sols.npy"),x_sols)
    np.save(Path("/scratch/gpfs/iywang/mro_results/" + foldername + "/X_sols.npy"),X_sols)
    np.save(Path("/scratch/gpfs/iywang/mro_results/" + foldername + "/Opt_vals.npy"),Opt_vals)
    np.save(Path("/scratch/gpfs/iywang/mro_results/" + foldername + "/solvetimes.npy"),solvetimes)
    np.save(Path("/scratch/gpfs/iywang/mro_results/" + foldername + "/clustertimes.npy"),clustertimes)
    np.save(Path("/scratch/gpfs/iywang/mro_results/" + foldername + "/setuptimes.npy"),setuptimes)
    np.save(Path("/scratch/gpfs/iywang/mro_results/" + foldername + "/probs.npy"),probs)
    np.save(Path("/scratch/gpfs/iywang/mro_results/" + foldername + "/probs1.npy"),probs1)

    plt.figure(figsize=(10, 6))
    for K_count, K in enumerate(K_nums):
        plt.plot(eps_nums, np.mean(Opt_vals[:,:,],axis = 2)[K_count,:],linestyle='-', marker='o', color = colors[K_count], label = "$K = {}$".format(round(K,4)))
        plt.xlabel("$\epsilon^2$")
    plt.xscale("log")
    plt.ylabel("Optimal value")
    plt.legend()
    plt.show()
    plt.savefig("/scratch/gpfs/iywang/mro_results/" + foldername + "/objs.png")

    plt.figure(figsize=(10, 6))
    for K_count, K in enumerate(K_nums):
        plt.plot(eps_nums, np.mean(probs[:,:,],axis = 2)[K_count,:],linestyle='-', marker='o', color = colors[K_count], label = "$K = {}$".format(round(K,4)))
        plt.xlabel("$\epsilon^2$")
    plt.xscale("log")
    plt.ylabel("Reliability")
    plt.legend()
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/' + foldername + '/reliability.png')

    plt.figure(figsize=(10, 6))
    for K_count, K in enumerate(K_nums):
        plt.plot(eps_nums, np.mean(probs1[:,:,],axis = 2)[K_count,:],linestyle='-', marker='o', color = colors[K_count], label = "$K = {}$".format(round(K,4)))
        plt.xlabel("$\epsilon^2$")
    plt.xscale("log")
    plt.ylabel("Reliability")
    plt.legend()
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/' + foldername + '/reliability1.png')

    plt.figure(figsize=(10, 6))
    for eps_count, eps in enumerate(eps_nums):
        plt.plot(K_nums,np.mean(solvetimes[:,:,],axis = 2)[:,eps_count],linestyle='-', marker='o', label = "$\epsilon^2 = {}$".format(round(eps,6)), alpha = 0.5)
        plt.xlabel("Number of clusters (K)")

    plt.ylabel("time")
    plt.title("Solve time")
    plt.legend()
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/' + foldername + '/solvetime.png')

    plt.figure(figsize=(10, 6))
    plt.plot(K_nums,np.mean(setuptimes + clustertimes,axis = 1),linestyle='-', marker='o')
    plt.xlabel("Number of clusters (K)")
    plt.ylabel("time")
    plt.title("Set-up time (clustering + creating problem)")
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/' + foldername + '/setuptime.png')

    plt.figure(figsize=(10, 6))
    for eps_count, eps in enumerate(eps_nums):
        plt.plot(K_nums,np.mean(setuptimes + clustertimes,axis = 1) + np.mean(solvetimes[:,:,],axis = 2)[:,eps_count],linestyle='-', marker='o', label = "$\epsilon^2 = {}$".format(round(eps,6)), alpha = 0.5)
        plt.xlabel("Number of clusters (K)")

    plt.ylabel("time")
    plt.title("Total time")
    plt.legend(fontsize=5)
    plt.show()
    plt.savefig('/scratch/gpfs/iywang/mro_results/' + foldername + '/totaltime.png')

    print("COMPLETE")

