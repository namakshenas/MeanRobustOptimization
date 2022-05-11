from pathlib import Path
from joblib import Parallel, delayed
import os
import mosek
from gurobipy import GRB
import gurobipy as gp
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
colors = ["tab:blue", "tab:orange", "tab:green",
          "tab:red", "tab:purple", "tab:brown", "tab:pink", "tab:grey", "tab:olive", "tab:blue", "tab:orange", "tab:green",
          "tab:red", "tab:purple", "tab:brown", "tab:pink", "tab:grey", "tab:olive"]


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


def createproblem_news1(N, m):
    """Creates the problem in cvxpy"""
    # m = 10
    # PARAMETERS #
    dat = cp.Parameter((N, m))
    eps = cp.Parameter()
    w = cp.Parameter(N)
    p = cp.Parameter(m)
    a = cp.Parameter(m)
    b = cp.Parameter(m)

    # VARIABLES #
    # weights, s_i, lambda, tau
    q = cp.Variable(m)
    s = cp.Variable(N)
    lam = cp.Variable()
    t = cp.Variable()
    y = cp.Variable(m)
    # OBJECTIVE #
    objective = t + a@q + 0.5*a@y

    # CONSTRAINTS #
    constraints = [cp.multiply(eps, lam) + w@s <= 0]
    constraints += [cp.hstack([-t]*N) + dat@(-p) +
                    cp.hstack([cp.quad_over_lin(p, 4*lam)]*N) <= s]
    constraints += [-p@q <= t, q - b <= y, 0 <=
                    y, a@q + 0.5*a@y <= 20, q >= 0, q <= 5*b]
    constraints += [lam >= 0]

    # PROBLEM #
    problem = cp.Problem(cp.Minimize(objective), constraints)
    return problem, q, p, a, b, t, lam, dat, eps, w


def createproblem_news(N, m):
    """Creates the problem in cvxpy, minimize CVaR"""
    # m = 10
    # PARAMETERS #
    dat = cp.Parameter((N, m))
    eps = cp.Parameter()
    w = cp.Parameter(N)
    p = cp.Parameter(m)
    a = cp.Parameter(m)
    b = cp.Parameter(m)
    a_1 = 50
    b_1 = -40
    #a_1 = 1
    #b_1 = 0

    # VARIABLES #
    # weights, s_i, lambda, tau
    q = cp.Variable(m)
    s = cp.Variable(N)
    lam = cp.Variable()
    t = cp.Variable()
    tao = cp.Variable()
    y = cp.Variable(m)
    # OBJECTIVE #
    objective = t

    # CONSTRAINTS #
    constraints = [cp.multiply(eps, lam) + w@s <= 0]
    constraints += [cp.hstack([-t + a_1*(a@q + 0.5*a@y) + b_1*tao]*N) + a_1*dat@(-p) +
                    cp.hstack([cp.quad_over_lin(a_1*p, 4*lam)]*N) <= s]
    constraints += [a_1*(-p@q + a@q + 0.5*a@y) + b_1*tao <= t]
    constraints += [10*tao <= t]
    constraints += [q - b <= y, 0 <= y, a@q + 0.5*a@y <= 20, q >= 0, q <= 5*b]
    constraints += [lam >= 0]

    # PROBLEM #
    problem = cp.Problem(cp.Minimize(objective), constraints)
    return problem, q, y, tao, p, a, b, t, lam, dat, eps, w


def generate_news_params(m=10):
    '''data for one problem instance of facility problem'''
    # Cost for facility
    a = np.random.uniform(0.2, 0.9, m)
    b = np.random.uniform(0.1, 0.7, m)
    F = np.random.normal(size=(m, 5))
    sig = 0.1*F@(F.T)
    mu = np.random.uniform(-0.2, 0, m)
    norms = np.random.multivariate_normal(mu, sig)
    p = np.exp(norms)
    return a, b, p, mu, sig


def generate_news_demands(mu, sig, N_tot, m=10, R_samples=30):
    '''generate uncertain demand'''
    norms = np.random.multivariate_normal(mu, sig, (R_samples, N_tot))
    #norms = np.random.normal(np.random.uniform(-0.2,0),0.2,(R_samples,N_tot,m))
    d_train = np.exp(norms)
    return d_train


def news_experiment(dat, dateval, r, m, a, b, p, prob, N_tot, K_tot, K_nums, eps_tot, eps_nums, foldername):
    '''run the experiment for multiple K and epsilon'''
    q_sols = np.zeros((K_tot, eps_tot, m, R))
    df = pd.DataFrame(columns=["K", "Epsilon", "Opt_val",
                               "satisfy", "solvetime", "clustertime", "setuptime"])
    Data = dat
    Data_eval = dateval

    ######################## Repeat experiment R times ########################
    ######################## solve for various K ########################
    for K_count, K in enumerate(K_nums):

        #output_stream.write('Percent Complete %.2f%s\r' % ((K_count)/K_tot*100,'%'))
        # output_stream.flush()
        if K == N_tot:
            d_train, wk = cluster_data(Data[r], K)
            clustertimes = 0
        else:
            tnow = time.time()
            d_train, wk = cluster_data(Data[r], K)
            clustertimes = time.time() - tnow
        evaldat = Data_eval[r]
        tnow = time.time()
        problem, q, y, tao, p_pm, a_pm, b_pm, t, lam_pm, dat_pm, eps_pm, w_pm = prob(
            K, m)
        a_pm.value = np.array(a)
        b_pm.value = np.array(b)
        p_pm.value = np.array(p)
        dat_pm.value = d_train
        w_pm.value = wk
        setuptimes = time.time() - tnow

        ######################## solve for various epsilons ########################
        for eps_count, eps in enumerate(eps_nums):
            eps_pm.value = eps
            problem.solve(ignore_dpp=True)
            # , solver = cp.MOSEK, verbose = True, mosek_params = {mosek.dparam.optimizer_max_time:  1000.0}
            q_sols[K_count, eps_count, :, r] = q.value
            evalvalue = -50*np.mean(evaldat@p_pm.value) + 50 * \
                (a@q.value + 0.5*a@y.value) - 40*tao.value - t.value <= 0
            #evalvalue = -np.mean(evaldat@p_pm.value) + (a@q.value + 0.5*a@y.value) - t.value <= 0
            #evalvalue = -np.mean(evaldat@p_pm.value) <= t.value
            newrow = pd.Series(
                {"K": K,
                 "Epsilon": eps,
                 "Opt_val": problem.objective.value,
                 "satisfy": evalvalue,
                 "solvetime": problem.solver_stats.solve_time,
                 "clustertime": clustertimes,
                 "setuptime": setuptimes
                 })
            df = df.append(newrow, ignore_index=True)

            df.to_csv('/scratch/gpfs/iywang/mro_results/' +
                      foldername + '/df.csv')

    return q_sols, df


if __name__ == '__main__':
    foldername = "newsvendor/cont/test"
    K_nums = np.array([1, 10, 50, 100, 300, 500])
    K_tot = K_nums.size  # Total number of clusters we consider
    N_tot = 500
    M = 10
    R = 10
    m = 40
    eps_min = -3    # minimum epsilon we consider
    eps_max = 0        # maximum epsilon we consider
    eps_nums = np.linspace(eps_min, eps_max, M)
    eps_nums = 10**(eps_nums)
    eps_tot = M
    a, b, p, mu, sig = generate_news_params(m)

    dat = generate_news_demands(mu, sig, N_tot, m, R)
    dateval = generate_news_demands(mu, sig, N_tot, m, R)
    njobs = get_n_processes(30)

    results = Parallel(n_jobs=njobs)(delayed(news_experiment)(dat, dateval, r, m, a, b, p,
                                                              createproblem_news, N_tot, K_tot, K_nums, eps_tot, eps_nums, foldername) for r in range(R))

    q_sols = np.zeros((K_tot, eps_tot, m, R))

    for r in range(R):
        q_sols += results[r][0]
    dftemp = results[0][1]
    for r in range(1, R):
        dftemp = dftemp.add(results[r][1].reset_index(), fill_value=0)
    dftemp = dftemp/R

    np.save(Path("/scratch/gpfs/iywang/mro_results/" +
            foldername + "/q_sols.npy"), q_sols)

    dftemp.to_csv('/scratch/gpfs/iywang/mro_results/' + foldername + '/df.csv')

    print("COMPLETE")
