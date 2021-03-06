"""
Project:
    Imperial College London MRes Dissertation Project (2017-18)

Description:
    We consider a robust multi-stage portfolio framework for optimising conditional value at risk (CVaR). During the
    first-stage, robustness is ensured by considering an ellipsoid uncertainty set for the corresponding expected
    returns. Subsequent stages are modelled using a robust framework with a (discrete) set of rival scenario trees.
    The first-stage essentially leads to a semi-infinite optimisation problem that can be simplified using duality
    to a second-order cone program. The discrete set of rival scenario trees in subsequent stages lead to discrete
    minimax. For large-scale scenario trees, Benders decomposition is needed. Past backtests with rival scenario
    trees have consistently yielded favourable results. The project will implement and test the basic model and
    subsequently consider its variants.

Authors:
  Sven Sabas

Date:
  23/05/2018
"""


# ------------------------------ IMPORT LIBRARIES --------------------------------- #

import pandas as pd
import numpy as np
import os
import sys

# Add the python scripts folder to system path
sys.path.insert(0, os.getcwd() + '/code/python')

from A_Data_Import import *
from B_Moment_Estimation import *
from C_Simulation import *
from D_CPLEX_Solver import *
from E_Evaluation import *

# -------------------- VARIABLES ----------------------------------------------------- #

input_file = 'moment_estimations'
output_file = 'scenario_tree'
simulations = 100000
nr_scenarios = 1
branching = (2, 8, 8, 8)
instruments_NYSE = ['KO', 'MSFT', 'IBM', 'AXP', 'PG', 'DIS', 'INTC', 'FDX', 'ADM', 'MAT']
instruments_FTSE = ['HSBC', 'VOD', 'BP', 'GSK', 'AZN', 'RIO', 'BG', 'TSCO', 'BT', 'PRU']
instruments = instruments_NYSE #+ instruments_FTSE
start_date = '2005-01-01'
end_date = '2017-01-01'
source = 'morningstar'
price_point = 'Close'
to_plot = 'yes'
to_save = 'yes'
initial_portfolio = np.repeat(1/len(instruments), len(instruments)) # Equally weighted portfolio
beta = 0.99
cost_to_sell = 0.01
cost_to_buy = 0.01
initial_wealth = 1
return_target = 1.01
solver = 'gurobi'
frequency = 'weekly'
look_back_period = 50
input_file = 'moment_estimation'
benchmark = 'yes'
periods_to_forecast = 25
return_points = 20
samples = 10
min_max_adjustment = 0.8
folder_portfolio_multi = 'portfolio_optimisation_%s_weeks_multi' % (periods_to_forecast)
folder_portfolio = 'portfolio_optimisation_%s_weeks' % (periods_to_forecast)
folder_ef = 'efficient_frontier_%s_scenarios_TEST' % (nr_scenarios)
folder_cvar_var = 'eff_port_var_test_%s_steps_%s_samples_%s_branching_%s_trees' % (return_points, samples,
                                                                                   ''.join(str(i) for i in branching),
                                                                                   nr_scenarios)


# Bounds for optimisation
sell_bounds = [[0.0], [0.2]]
buy_bounds = [[0.0], [0.2]]
weight_bounds = [[0.0], [1.0]]

# Improves readability (extends)
pd.set_option('display.max_columns', 10)

# -------------------- EXECUTING C++ CODE THROUGH PYTHON ----------------------------- #

# Get the data
stock_data = import_stock_data_api(instruments=instruments, data_source=source,
                                   start_date=start_date, end_date=end_date, price_point=price_point,
                                   to_plot=to_plot, to_save=to_save, from_file='no', folder=folder_cvar_var,
                                   frequency=frequency)  # Takes c. 20 secs to query

# # Test exponential fit for a single stock
# residuals, parameters = exponential_growth(stock_data['VOD'], to_plot=to_plot)
#
# # Test moment-calculation
# means, variances = calculate_moments(stock_data)
#
# # Get the moments and save to format for the simulator
# put_to_cpp_layout(folder_ef, input_file, stock_data, branching=branching)
#
# # Run the simulation
# # clean_cluster() # In case first run
# # compile_cluster() # Gives some errors, but still works
# run_cluster(input_file, output_file, folder_ef, samples=simulations, scenario_trees=nr_scenarios)
#
# # Read the output
# scenarios_dict = read_cluster_output(output_file, folder_ef, scenario_trees=nr_scenarios, asset_names=instruments)
#
# # Get the final cumulative probabilities
# scenarios_dict = add_cumulative_probabilities(scenarios_dict, branching)
#
# # Plot the simulation output for sense-checking
# output = {}
# output_cum = {}
# for i in instruments:
#     print(i)
#     output[i], output_cum[i] = plot_cluster_output(stock_data, i, scenarios_dict['1'], branching, to_plot='yes')
#
# # Get minimum return
# min_return = robust_portfolio_optimisation(scenarios_dict, instruments, branching, initial_portfolio, sell_bounds,
#                                            buy_bounds, weight_bounds, cost_to_buy=cost_to_buy, cost_to_sell=cost_to_sell,
#                                            beta=beta, initial_wealth=initial_wealth, to_save='no', folder=folder_ef,
#                                            solver='cplex', wcvar_minimizer='yes') # Use CPLEX for minimization
#
# # Get maximum return
# max_return = return_maximisation(scenarios_dict, instruments, branching, initial_portfolio, sell_bounds, buy_bounds,
#                                  weight_bounds, cost_to_buy=cost_to_buy, cost_to_sell=cost_to_sell, beta=beta,
#                                  initial_wealth=initial_wealth, folder=folder_ef, solver='gurobi')
#
# # Construct return sequence
# returns = np.linspace(min_return['return'], max(max_return.values()), 20)

# Create an efficient frontier
ef_wcvars = efficient_frontier(stock_data, branching, initial_portfolio, simulations=simulations,
                               return_points=return_points,
                               nr_scenarios=nr_scenarios, sell_bounds=sell_bounds, buy_bounds=buy_bounds,
                               weight_bounds=weight_bounds, cost_to_buy=cost_to_buy, cost_to_sell=cost_to_sell,
                               beta=beta, initial_wealth=initial_wealth, to_plot=to_plot, folder=folder_ef, solver=solver,
                               to_save=to_save)

# Calculate the optimised portfolio
output = portfolio_optimisation(stock_data, look_back_period, folder=folder_portfolio,
                                periods_to_forecast=periods_to_forecast, input_file=input_file, frequency=frequency,
                                benchmark=benchmark, to_plot=to_plot, to_save=to_save, branching=branching,
                                simulations=simulations, initial_portfolio=initial_portfolio, nr_scenarios=nr_scenarios,
                                return_target=return_target, sell_bounds=sell_bounds, buy_bounds=buy_bounds,
                                weight_bounds=weight_bounds, cost_to_buy=cost_to_buy, cost_to_sell=cost_to_sell,
                                beta=beta, initial_wealth=initial_wealth, solver=solver)

# Run the portfolio optimisation multiple times
output_dict = portfolio_optimisation_variance_testing(stock_data, look_back_period, folder=folder_portfolio_multi,
                                                      periods_to_forecast=periods_to_forecast, input_file=input_file, frequency=frequency,
                                                      benchmark=benchmark, to_plot=to_plot, to_save=to_save, branching=branching,
                                                      simulations=simulations, initial_portfolio=initial_portfolio, nr_scenarios=nr_scenarios,
                                                      return_target=return_target, sell_bounds=sell_bounds, buy_bounds=buy_bounds,
                                                      weight_bounds=weight_bounds, cost_to_buy=cost_to_buy, cost_to_sell=cost_to_sell,
                                                      beta=beta, initial_wealth=initial_wealth, solver=solver, iterations=iterations)

# Test the variance of CVaR optimisation
return_cvar_df = efficient_portfolio_variance_testing(stock_data, branching, initial_portfolio, simulations=simulations,
                                                      return_points=return_points, nr_scenarios=nr_scenarios,
                                                      sell_bounds=sell_bounds,
                                                      buy_bounds=buy_bounds, weight_bounds=weight_bounds,
                                                      cost_to_buy=cost_to_buy, cost_to_sell=cost_to_sell,
                                                      beta=beta, initial_wealth=initial_wealth, solver=solver,
                                                      folder=folder_cvar_var,
                                                      to_plot=to_plot, to_save=to_save,
                                                      input_file=input_file, min_return=None, max_return=None,
                                                      samples=samples, min_max_adjustment=min_max_adjustment)

compare_efficient_frontier_variance_tests('eff_port_var_test_20_steps_10_samples_2888_branching_1_trees',
                                          'eff_port_var_test_20_steps_10_samples_2288_branching_4_trees',
                                          'eff_port_var_test_20_steps_10_samples_2288_branching_1_trees')

# # Do 4 runs for optimising portfolio
# folder_portfolio = folder_portfolio + '/test_1'
# output = portfolio_optimisation(stock_data, look_back_period, start_date, end_date, folder=folder_portfolio,
#                                 periods_to_forecast=periods_to_forecast, input_file=input_file, frequency=frequency,
#                                 benchmark=benchmark, to_plot=to_plot, to_save=to_save, branching=branching,
#                                 simulations=simulations, initial_portfolio=initial_portfolio, nr_scenarios=nr_scenarios,
#                                 return_target=return_target, sell_bounds=sell_bounds, buy_bounds=buy_bounds,
#                                 weight_bounds=weight_bounds, cost_to_buy=cost_to_buy, cost_to_sell=cost_to_sell,
#                                 beta=beta, initial_wealth=initial_wealth, solver=solver)
#
# output_dict = {}
# output_dict['1'] = output
# folder_portfolio = 'portfolio_optimisation_%s_weeks_multi' %(periods_to_forecast)
# for i in range(2,5):
#     print(i)
#     folder = folder_portfolio + '/test_%s' %i
#     print(folder)
#     output_dict[str(i)] = portfolio_optimisation(stock_data, look_back_period, start_date, end_date, folder=folder,
#                                     periods_to_forecast=periods_to_forecast, input_file=input_file, frequency=frequency,
#                                     benchmark=benchmark, to_plot=to_plot, to_save=to_save, branching=branching,
#                                     simulations=simulations, initial_portfolio=initial_portfolio, nr_scenarios=nr_scenarios,
#                                     return_target=return_target, sell_bounds=sell_bounds, buy_bounds=buy_bounds,
#                                     weight_bounds=weight_bounds, cost_to_buy=cost_to_buy, cost_to_sell=cost_to_sell,
#                                     beta=beta, initial_wealth=initial_wealth, solver=solver)

# Plot the results in coherent way.

# output_dict = {}
# for i in range(1, 5):
#     print(i)
#     folder = folder_portfolio+ '_multitest/test_%s' %i
#     output_dict[str(i)] = portfolio_optimisation(stock_data, look_back_period, start_date, end_date, folder=folder,
#                                 periods_to_forecast=periods_to_forecast, input_file=input_file, frequency=frequency,
#                                 benchmark=benchmark, to_plot=to_plot, to_save=to_save, branching=branching,
#                                 simulations=simulations, initial_portfolio=initial_portfolio, nr_scenarios=nr_scenarios,
#                                 return_target=return_target, sell_bounds=sell_bounds, buy_bounds=buy_bounds,
#                                 weight_bounds=weight_bounds, cost_to_buy=cost_to_buy, cost_to_sell=cost_to_sell,
#                                 beta=beta, initial_wealth=initial_wealth, solver=solver)



# Save the workspace variables to file


# # Plot area plot for weights
# output = pd.read_csv(os.getcwd() + '/results/' + folder_portfolio + '/optimised_portfolio_data.csv',
#                      index_col=0, parse_dates=True)
# output.plot.area(figsize=(9, 6))
# plt.title('Min-Max CVaR Optimised Portfolio Weights')
# plt.ylabel('Portfolio Value')
# plt.xlabel('Date')
# plt.tight_layout()
# plt.savefig(os.getcwd() + '/results/' + folder_portfolio + '/optimised_portfolio_weights.pdf')
#
# df = output.divide(output.sum(axis=1), axis=0)
# df.plot.area(figsize=(9, 6))
# plt.title('Min-Max CVaR Optimised Portfolio Weights (Normalised)')
# plt.ylabel('Portfolio Value')
# plt.xlabel('Date')
# plt.tight_layout()
# plt.savefig(os.getcwd() + '/results/' + folder_portfolio + '/optimised_portfolio_weights_normalised.pdf')
