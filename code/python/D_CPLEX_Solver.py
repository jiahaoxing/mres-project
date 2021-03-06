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

import cplex
import numpy as np
from operator import mul
from functools import reduce
import pandas as pd
from gurobipy import *

# ------------------------------ DEFINE THE PROGRAM ------------------------------- #


def robust_portfolio_optimisation(scenarios_dict, instruments, branching, initial_portfolio,
                                  sell_bounds, buy_bounds, weight_bounds, cost_to_buy=0.01, cost_to_sell=0.01,
                                  beta=0.95, initial_wealth=1, return_target=1.08, to_save='no', folder='',
                                  solver='gurobi', wcvar_minimizer='no'):

    # Initialise the object
    min_wcvar = cplex.Cplex()

    # Set as minimisation problem
    min_wcvar.objective.set_sense(min_wcvar.objective.sense.minimize)

    # Get quantities required to define variables
    scenario_names = list(scenarios_dict.keys())
    nr_trees = len(scenarios_dict.keys()) # K variable in the model
    nr_time_periods = len(branching)+1  # Includes first time period (t=0)
    nr_scenarios = reduce(mul, branching[1:], 1) # S variable in the model
    final_nodes = list(scenarios_dict[scenario_names[0]][scenarios_dict[scenario_names[0]].node.str.len()== (nr_time_periods-1)]['node'])
    internal_nodes = list(scenarios_dict[scenario_names[0]][scenarios_dict[scenario_names[0]].node.str.len() < (nr_time_periods-1)]['node'])
    all_nodes = list(scenarios_dict[scenario_names[0]]['node'])

    #### VARIABLES ####

    # Define variables - weights for all assets, z variable for all scenarios and var
    wcvar = 'wcvar'
    var = ['var_' + str(k) for k in scenarios_dict.keys()]

    # For period t=0 (same for all scenarios)
    w0_asset_weights = ["w_0_" + str(j) for j in instruments]
    w0_asset_buys = ["b_0_" + str(j) for j in instruments]
    w0_asset_sells = ["s_0_" + str(j) for j in instruments]
    # w0_all_variables = [*w0_asset_weights, *w0_asset_buys, *w0_asset_sells]

    # For periods t= 1, ..., T-1
    z = ["z_k" + str(k) + "_s" + str(s) for k in scenarios_dict.keys() for s in final_nodes] #
    asset_weights = ["w_k" + str(k) + "_" + str(i) + "_s" + str(s) for k in scenarios_dict.keys() for i in instruments for s in internal_nodes]
    asset_buys = ["b_k" + str(k) + "_" + str(i) + "_s" + str(s) for k in scenarios_dict.keys() for i in instruments for s in internal_nodes]
    asset_sells = ["s_k" + str(k) + "_" + str(i) + "_s" + str(s) for k in scenarios_dict.keys() for i in instruments for s in internal_nodes]
    all_variables = list([wcvar, *var, *z, *w0_asset_weights, *asset_weights,
                          *w0_asset_buys, *asset_buys, *w0_asset_sells, *asset_sells])

    # Set bounds for variables
    wcvar_bounds = [[0.0], [cplex.infinity]]
    var_bounds = [np.repeat(0.0, len(var)), np.repeat(1e20, len(var))]
    z_bounds = [np.repeat(0.0,len(z)), np.repeat(1e20, len(z))]
    all_weight_bounds = [np.repeat(weight_bounds[0], len(w0_asset_weights) + len(asset_weights)),
                         np.repeat(weight_bounds[1], len(w0_asset_weights) + len(asset_weights))]
    all_sell_bounds = [np.repeat(sell_bounds[0], len(w0_asset_sells) + len(asset_sells)),
                       np.repeat(sell_bounds[1], len(w0_asset_sells) + len(asset_sells))]
    all_buy_bounds = [np.repeat(buy_bounds[0], len(w0_asset_buys) + len(asset_buys)),
                      np.repeat(buy_bounds[1], len(w0_asset_buys) + len(asset_buys))]
    all_lower_bounds = list([*wcvar_bounds[0], *var_bounds[0], *z_bounds[0],
                             *all_weight_bounds[0], *all_buy_bounds[0], *all_sell_bounds[0]])
    all_upper_bounds = list([*wcvar_bounds[1], *var_bounds[1], *z_bounds[1],
                             *all_weight_bounds[1], *all_buy_bounds[1], *all_sell_bounds[1]])

    #### OBJECTIVE FUNCTION ####
    print('Specifying objective function.')
    objective_function = list([1.0, *np.repeat(0.0, len(all_variables)-1)])

    # Define variables and objective function
    min_wcvar.variables.add(names=all_variables,
                            obj=objective_function,
                            lb=all_lower_bounds,
                            ub=all_upper_bounds)

    ######################### CONSTRAINTS #############################

    ### Period t=0 constraints
    print('Adding period t=0 constraints.')
    # For each asset a separate row is needed for t=0 weight
    for i, j in zip(instruments, range(len(instruments))): # j is to loop over the initial_portfolio list
        # print(i, j)
        asset = 'w_0_' + i
        to_buy = 'b_0_' + i
        to_sell = 's_0_' + i
        w_0_variables = [asset, to_buy, to_sell]
        w_0_values = [1.0, -(1.0-cost_to_buy), 1.0+cost_to_sell]
        min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=w_0_variables, val=w_0_values)],
                                         senses=["E"],
                                         rhs=[initial_portfolio[j]],
                                         names=[asset])
        # Equivalent to p + (1-c_b)*b_0 - (1+c_s)*s_0 = w_0

    # Normalise weights to 1 at t=0
    # w0_asset_buys = ["b_0_" + str(j) for j in instruments]
    # w0_asset_sells = ["s_0_" + str(j) for j in instruments]
    w_0_variables = [*w0_asset_buys, *w0_asset_sells]
    w_0_values = [*np.repeat(1.0, len(w0_asset_buys)), *np.repeat(-1.0, len(w0_asset_sells))]
    min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=w_0_variables, val=w_0_values)],
                                     senses=["E"],
                                     rhs=[1.0-np.sum(initial_portfolio)],
                                     names=["w_0_balance_constraint"])

    ### Constraints for the intermediate periods t = 1, ...., T-1
    print('Adding period t=1, ..., T-1 constraints (intermediate nodes).')
    # Weights constraint, taking into account the return
    for k in scenarios_dict:
        # print(k)
        for instrument in instruments:
            for node in internal_nodes:

                return_constraint_variables = []

                # Take the weight from previous period
                if len(node) == 1:  # Takes the 0th period weight
                    # print(t)
                    return_constraint_variables.append('w_0_' + instrument)

                else:
                    return_constraint_variables.append(
                        'w_k' + str(k) + "_" + instrument + "_s" + str(node)[:-1])

                # Take the buys and sells from current period
                return_constraint_variables.append('b_k' + str(k) + "_" + instrument + "_s" + str(node))
                return_constraint_variables.append('s_k' + str(k) + "_" + instrument + "_s" + str(node))

                # Deduct the current rating (to have right side 0)
                return_constraint_variables.append('w_k' + str(k) + "_" + instrument + "_s" + str(node))

                # Get the parameters
                return_constraint_parameters = [0.0, 1.0 - cost_to_buy, -(1.0 + cost_to_sell), -1.0]
                return_constraint_parameters[0] = float(scenarios_dict[str(k)][scenarios_dict[str(k)]['node'] == str(node)][instrument])

                # Set constraints
                min_wcvar.linear_constraints.add(
                    lin_expr=[cplex.SparsePair(ind=return_constraint_variables, val=return_constraint_parameters)],
                    senses=["E"],
                    rhs=[0.0],
                    names=[return_constraint_variables[-1] + "_return_constraint"])

    # Buy-sell balance constraints
    for k in scenarios_dict:
            for node in internal_nodes:

                asset_buys = ['b_k' + str(k) + "_" + instrument + "_s" + str(node) for instrument in instruments]
                asset_sells = ['s_k' + str(k) + "_" + instrument + "_s" + str(node) for instrument in instruments]
                balance_constraint_variables = [*asset_buys, *asset_sells]
                balance_constraint_parameters = [*np.repeat(1.0, len(asset_buys)), *np.repeat(-1.0, len(asset_sells))]

                # Set the constraints
                min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=balance_constraint_variables, val=balance_constraint_parameters)],
                                                 senses=["E"],
                                                 rhs=[0.0],
                                                 names=['k' + str(k) + "_s" + str(node) + "_balance_constraint"])

    # WCVAR constraints for each scenario
    print('Adding WCVAR constraints.')
    for k in scenarios_dict:
        # print(k)
        wcvar_constraint_variables = ['wcvar', 'var_' + str(k),
                                      *["z_k" + str(k) + "_s" + str(node) for node in final_nodes]]
        z_parameters = scenarios_dict[str(k)][scenarios_dict[str(k)]['node'].isin(final_nodes)]['cum_probability'].astype(float)
        z_parameters = np.array(z_parameters) * (-1/(1-beta))
        wcvar_contraint_parameters = [1.0, -1.0, *z_parameters]

        min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=wcvar_constraint_variables, val=wcvar_contraint_parameters)],
                                         senses=["G"],
                                         rhs=[0.0],
                                         names=["k%s_wcvar_constraint" %k])

    # z constraint for each scenario
    print('Adding z (CVaR) constraints.')
    for k in scenarios_dict:
        for node in final_nodes:

            z = "z_k" + str(k) + "_s" + str(node)
            z_constraint_variables = [z]
            z_constraint_parameters = [1.0]

            for instrument in instruments:

                z_constraint_variables.append(*['w_k' + str(k) + "_" + instrument + "_s" + str(node)[:-1]])
                z_constraint_parameters.append(*[float(scenarios_dict[str(k)][scenarios_dict[str(k)]['node'] == str(node)][instrument]) * initial_wealth])

            z_constraint_variables.append(*['var_' + str(k)])
            z_constraint_parameters.append(*[1.0])

            min_wcvar.linear_constraints.add(
                lin_expr=[cplex.SparsePair(ind=z_constraint_variables, val=z_constraint_parameters)],
                senses=["G"],
                rhs=[initial_wealth],
                names=[z + "_constraint"])

    # If we want to minimise wcvar, then we do not impose any return constraints
    if wcvar_minimizer == 'no':

        # Return constraint for period t = T
        print('Adding period t = T return constraints.')
        for k in scenarios_dict:
            # print(k)
            return_constraint_variables = []
            return_constraint_parameters = []

            for node in final_nodes:
                # print(node)
                return_constraint_variables.append(['w_k' + str(k) + "_" + instrument + "_s" + str(node)[:-1] for instrument in instruments])
                return_constraint_parameters.append(np.array(scenarios_dict[str(k)][scenarios_dict[str(k)]['node'] == str(node)].T[2:-1].T.astype(float)\
                                               * float(scenarios_dict[str(k)][scenarios_dict[str(k)]['node'] == str(node)]['cum_probability'])).flatten())

            # Flatten the lists
            return_constraint_variables = [item for sublist in return_constraint_variables for item in sublist]
            return_constraint_parameters = [item for sublist in return_constraint_parameters for item in sublist]

            # Put to dataframe and then group by weight (sum it)
            # Define the dataframe to be populated
            data_dict = {'variables': return_constraint_variables, 'values': return_constraint_parameters}
            data_df = pd.DataFrame(data=data_dict)
            data_grouped = data_df.groupby(['variables'])['values'].sum()
            return_constraint_variables = data_grouped.index
            return_constraint_parameters = data_grouped.values

            # Set constraint such that the return is over certain threshold
            min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=return_constraint_variables, val=return_constraint_parameters)],
                                             senses=["G"],
                                             rhs=[return_target],
                                             names=['k' + str(k) + "_return_constraint"])

    if solver == 'gurobi':

        # Need to write CPLEX LP to file and then export as a gurobi file
        min_wcvar.write(os.getcwd() + "/results/" + folder + "/robust_optimisation_programme.lp")

        # Run gurobi solver
        lp_file = read(os.getcwd() + "/results/" + folder + "/robust_optimisation_programme.lp")
        presolved_lp = lp_file.presolve()
        presolved_lp.optimize()

        if presolved_lp.Status == GRB.OPTIMAL:
            # Get variables and objective
            objective_value = presolved_lp.ObjVal
            w_0_variables = [x.varName for x in presolved_lp.getVars() if x.VarName.find('w_0') != -1]
            w_0_values = [x.x for x in presolved_lp.getVars() if x.VarName.find('w_0') != -1]
            # solution = presolved_lp.getVars()

        else:
            print('Not primal feasible.')
            objective_value = np.nan
            w_0_values = np.nan
            w_0_variables = np.nan

    if solver == 'cplex':

        min_wcvar.solve()
        # min_wcvar.solution.is_primal_feasible()

        if min_wcvar.solution.is_primal_feasible():
            objective_value = min_wcvar.solution.get_objective_value()
            indices = [min_wcvar.variables.get_names().index(i) for i in w0_asset_weights]
            w_0_values = [min_wcvar.solution.get_values()[index] for index in indices]
            w_0_variables = w0_asset_weights

        else:
            print('Not primal feasible.')
            objective_value = np.nan
            w_0_values = np.nan
            w_0_variables = np.nan

        if wcvar_minimizer == 'yes':
            print('Finding the scenario with maximum CVaR (solution to the min-max problem).')

            # Find the scenario with minimum risk
            wcvar_dict = {}
            for k in scenarios_dict:
                # print(k)
                wcvar_constraint_variables = ['var_' + str(k),
                                              *["z_k" + str(k) + "_s" + str(node) for node in final_nodes]]
                z_parameters = scenarios_dict[str(k)][scenarios_dict[str(k)]['node'].isin(final_nodes)][
                    'cum_probability'].astype(float)
                z_parameters = np.array(z_parameters) * (-1 / (1 - beta))
                wcvar_contraint_parameters = [-1.0, *z_parameters]

                # Get the variable values in the end
                wcvar_indices = [min_wcvar.variables.get_names().index(i) for i in wcvar_constraint_variables]
                wcvar_values = [min_wcvar.solution.get_values()[index] for index in wcvar_indices]

                # Get wcvars
                wcvar_dict[k] = -np.sum(np.array(wcvar_contraint_parameters) * np.array(wcvar_values))

            # Get the scenario with minimum CVaR
            k = max(wcvar_dict, key=wcvar_dict.get)
            print('The minimum CVaR (%.3f) is based on scenario %s.' % (objective_value, k))

            # Get the return
            return_constraint_variables = []
            return_constraint_parameters = []

            for node in final_nodes:
                # print(node)
                return_constraint_variables.append(
                    ['w_k' + str(k) + "_" + instrument + "_s" + str(node)[:-1] for instrument in instruments])
                return_constraint_parameters.append(
                    np.array(scenarios_dict[str(k)][scenarios_dict[str(k)]['node'] == str(node)].T[2:-1].T.astype(float) \
                             * float(
                        scenarios_dict[str(k)][scenarios_dict[str(k)]['node'] == str(node)]['cum_probability'])).flatten())

            # Flatten the lists
            return_constraint_variables = [item for sublist in return_constraint_variables for item in sublist]
            return_constraint_parameters = [item for sublist in return_constraint_parameters for item in sublist]

            # Put to dataframe and then group by weight (sum it)
            # Define the dataframe to be populated
            data_dict = {'variables': return_constraint_variables, 'values': return_constraint_parameters}
            data_df = pd.DataFrame(data=data_dict)
            data_grouped = data_df.groupby(['variables'])['values'].sum()
            return_constraint_variables = data_grouped.index
            return_constraint_parameters = data_grouped.values

            # Get the variable values in the end
            # print('Getting indices')
            indices = [min_wcvar.variables.get_names().index(i) for i in return_constraint_variables]
            # print('Getting values')
            values = [min_wcvar.solution.get_values()[index] for index in indices]

            # Get return
            min_return = np.sum(return_constraint_parameters * values)
            print("The scenario has return of %0.3f." % min_return)

            if to_save == 'yes':
                print('Writing the LP to file.')

                if not os.path.exists(os.getcwd() + '/results/' + folder):
                    os.makedirs(os.getcwd() + '/results/' + folder)

                min_wcvar.write(os.getcwd() + "/results/" + folder + "/robust_optimisation_programme.lp")

            return {'wcvar': objective_value, 'return': min_return,
                    'w_0_variables': w_0_variables, 'w_0_values': w_0_values}

    # Write to file
    if to_save == 'yes':
        print('Writing the LP to file.')

        if not os.path.exists(os.getcwd() + '/results/' + folder):
                os.makedirs(os.getcwd() + '/results/' + folder)

        min_wcvar.write(os.getcwd() + "/results/" + folder + "/robust_optimisation_programme.lp")

    return objective_value, w_0_variables, w_0_values # min_wcvar, w_0_solution, w0_asset_weights


def return_maximisation(scenarios_dict, instruments, branching, initial_portfolio,
                        sell_bounds, buy_bounds, weight_bounds, cost_to_buy=0.01, cost_to_sell=0.01,
                        beta=0.95, initial_wealth=1, return_target=1.08, to_save='no', folder='',
                        solver='gurobi'):

    # Create dictionary of dictionaries for testing and also the results dictionary
    test_dict = {}
    results = {}
    for tree in scenarios_dict:
        # print(tree)
        test_dict[tree] = {tree: scenarios_dict[tree]}
        results[tree] = []

    # Iterate over scenarios
    for scenario in scenarios_dict:

        print('Scenario number %s (out of %s).' %(scenario, len(scenarios_dict)))
        data = test_dict[scenario]

        # Initialise the object
        max_return = cplex.Cplex()

        # Set as minimisation problem
        max_return.objective.set_sense(max_return.objective.sense.maximize)

        # Get quantities required to define variables
        scenario_names = list(data.keys())
        nr_trees = len(data.keys()) # K variable in the model
        nr_time_periods = len(branching)+1  # Includes first time period (t=0)
        nr_scenarios = reduce(mul, branching[1:], 1) # S variable in the model
        final_nodes = list(data[scenario_names[0]][data[scenario_names[0]].node.str.len()== (nr_time_periods-1)]['node'])
        internal_nodes = list(data[scenario_names[0]][data[scenario_names[0]].node.str.len() < (nr_time_periods-1)]['node'])
        all_nodes = list(data[scenario_names[0]]['node'])

        #### VARIABLES ####

        # Define variables - weights for all assets, z variable for all scenarios and var
        opt_return = 'opt_return'

        # For period t=0 (same for all scenarios)
        w0_asset_weights = ["w_0_" + str(j) for j in instruments]
        w0_asset_buys = ["b_0_" + str(j) for j in instruments]
        w0_asset_sells = ["s_0_" + str(j) for j in instruments]
        # w0_all_variables = [*w0_asset_weights, *w0_asset_buys, *w0_asset_sells]

        # For periods t= 1, ..., T-1
        asset_weights = ["w_k" + str(k) + "_" + str(i) + "_s" + str(s) for k in data.keys() for i in instruments for s in internal_nodes]
        asset_buys = ["b_k" + str(k) + "_" + str(i) + "_s" + str(s) for k in data.keys() for i in instruments for s in internal_nodes]
        asset_sells = ["s_k" + str(k) + "_" + str(i) + "_s" + str(s) for k in data.keys() for i in instruments for s in internal_nodes]
        all_variables = list([opt_return, *w0_asset_weights, *asset_weights, *w0_asset_buys,
                              *asset_buys, *w0_asset_sells, *asset_sells])

        # Set bounds for variables
        opt_return_bounds = [[0.0], [cplex.infinity]]
        all_weight_bounds = [np.repeat(weight_bounds[0], len(w0_asset_weights) + len(asset_weights)),
                             np.repeat(weight_bounds[1], len(w0_asset_weights) + len(asset_weights))]
        all_sell_bounds = [np.repeat(sell_bounds[0], len(w0_asset_sells) + len(asset_sells)),
                           np.repeat(sell_bounds[1], len(w0_asset_sells) + len(asset_sells))]
        all_buy_bounds = [np.repeat(buy_bounds[0], len(w0_asset_buys) + len(asset_buys)),
                          np.repeat(buy_bounds[1], len(w0_asset_buys) + len(asset_buys))]
        all_lower_bounds = list([*opt_return_bounds[0], *all_weight_bounds[0], *all_buy_bounds[0], *all_sell_bounds[0]])
        all_upper_bounds = list([*opt_return_bounds[1], *all_weight_bounds[1], *all_buy_bounds[1], *all_sell_bounds[1]])

        #### OBJECTIVE FUNCTION ####
        print('Specifying objective function.')
        objective_function = list([1.0, *np.repeat(0.0, len(all_variables)-1)])

        # Define variables and objective function
        max_return.variables.add(names=all_variables,
                                 obj=objective_function,
                                 lb=all_lower_bounds,
                                 ub=all_upper_bounds)

        ######################### CONSTRAINTS #############################

        ### Period t=0 constraints
        print('Adding period t=0 constraints.')
        # For each asset a separate row is needed for t=0 weight
        for i, j in zip(instruments, range(len(instruments))): # j is to loop over the initial_portfolio list
            # print(i, j)
            asset = 'w_0_' + i
            to_buy = 'b_0_' + i
            to_sell = 's_0_' + i
            w_0_variables = [asset, to_buy, to_sell]
            w_0_values = [1.0, -(1.0-cost_to_buy), 1.0+cost_to_sell]
            max_return.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=w_0_variables, val=w_0_values)],
                                              senses=["E"],
                                              rhs=[initial_portfolio[j]],
                                              names=[asset])
            # Equivalent to p + (1-c_b)*b_0 - (1+c_s)*s_0 = w_0

        # Normalise weights to 1 at t=0
        # w0_asset_buys = ["b_0_" + str(j) for j in instruments]
        # w0_asset_sells = ["s_0_" + str(j) for j in instruments]
        w_0_variables = [*w0_asset_buys, *w0_asset_sells]
        w_0_values = [*np.repeat(1.0, len(w0_asset_buys)), *np.repeat(-1.0, len(w0_asset_sells))]
        max_return.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=w_0_variables, val=w_0_values)],
                                          senses=["E"],
                                          rhs=[1.0-np.sum(initial_portfolio)],
                                          names=["w_0_balance_constraint"])

        ### Constraints for the intermediate periods t = 1, ...., T-1
        print('Adding period t=1, ..., T-1 constraints (intermediate nodes).')
        # Weights constraint, taking into account the return
        for k in data:
            # print(k)
            for instrument in instruments:
                for node in internal_nodes:

                    return_constraint_variables = []

                    # Take the weight from previous period
                    if len(node) == 1:  # Takes the 0th period weight
                        # print(t)
                        return_constraint_variables.append('w_0_' + instrument)

                    else:
                        return_constraint_variables.append(
                            'w_k' + str(k) + "_" + instrument + "_s" + str(node)[:-1])

                    # Take the buys and sells from current period
                    return_constraint_variables.append('b_k' + str(k) + "_" + instrument + "_s" + str(node))
                    return_constraint_variables.append('s_k' + str(k) + "_" + instrument + "_s" + str(node))

                    # Deduct the current rating (to have right side 0)
                    return_constraint_variables.append('w_k' + str(k) + "_" + instrument + "_s" + str(node))

                    # Get the parameters
                    return_constraint_parameters = [0.0, 1.0 - cost_to_buy, -(1.0 + cost_to_sell), -1.0]
                    return_constraint_parameters[0] = float(data[str(k)][data[str(k)]['node'] == str(node)][instrument])

                    # Set constraints
                    max_return.linear_constraints.add(
                        lin_expr=[cplex.SparsePair(ind=return_constraint_variables, val=return_constraint_parameters)],
                        senses=["E"],
                        rhs=[0.0],
                        names=[return_constraint_variables[-1] + "_return_constraint"])

        # Buy-sell balance constraints
        for k in data:
                for node in internal_nodes:

                    asset_buys = ['b_k' + str(k) + "_" + instrument + "_s" + str(node) for instrument in instruments]
                    asset_sells = ['s_k' + str(k) + "_" + instrument + "_s" + str(node) for instrument in instruments]
                    balance_constraint_variables = [*asset_buys, *asset_sells]
                    balance_constraint_parameters = [*np.repeat(1.0, len(asset_buys)), *np.repeat(-1.0, len(asset_sells))]

                    # Set the constraints
                    max_return.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=balance_constraint_variables, val=balance_constraint_parameters)],
                                                      senses=["E"],
                                                      rhs=[0.0],
                                                      names=['k' + str(k) + "_s" + str(node) + "_balance_constraint"])

        # Max-max problem
        # Return constraint for period t = T
        print('Adding period t = T return constraints.')
        for k in data:
            # print(k)
            return_constraint_variables = []
            return_constraint_parameters = []

            for node in final_nodes:
                # print(node)
                return_constraint_variables.append(['w_k' + str(k) + "_" + instrument + "_s" + str(node)[:-1] for instrument in instruments])
                return_constraint_parameters.append(np.array(data[str(k)][data[str(k)]['node'] == str(node)].T[2:-1].T.astype(float)\
                                               * float(data[str(k)][data[str(k)]['node'] == str(node)]['cum_probability'])).flatten())

            # Flatten the lists
            return_constraint_variables = [item for sublist in return_constraint_variables for item in sublist]
            return_constraint_parameters = [item for sublist in return_constraint_parameters for item in sublist]

            # Put to dataframe and then group by weight (sum it)
            # Define the dataframe to be populated
            data_dict = {'variables': return_constraint_variables, 'values': return_constraint_parameters}
            data_df = pd.DataFrame(data=data_dict)
            data_grouped = data_df.groupby(['variables'])['values'].sum()
            return_constraint_variables = [opt_return, *data_grouped.index]
            return_constraint_parameters = [1.0, *-data_grouped.values]

            # Set constraint such that the return is over certain threshold
            max_return.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=return_constraint_variables, val=return_constraint_parameters)],
                                              senses=["L"],
                                              rhs=[0.0],
                                              names=['k' + str(k) + "_return_constraint"])

        if solver == 'gurobi':

            # Need to write CPLEX LP to file and then export as a gurobi file
            max_return.write(os.getcwd() + "/results/" + folder + "/robust_optimisation_programme.lp")

            # Run gurobi solver
            lp_file = read(os.getcwd() + "/results/" + folder + "/robust_optimisation_programme.lp")
            presolved_lp = lp_file.presolve()
            presolved_lp.optimize()

            if presolved_lp.Status == GRB.OPTIMAL:
                # Get variables and objective
                objective_value = presolved_lp.ObjVal
                w_0_variables = [x.varName for x in presolved_lp.getVars() if x.VarName.find('w_0') != -1]
                w_0_values = [x.x for x in presolved_lp.getVars() if x.VarName.find('w_0') != -1]
                # solution = presolved_lp.getVars()

            else:
                print('Not primal feasible.')
                objective_value = np.nan
                w_0_values = np.nan
                w_0_variables = np.nan

        if solver == 'cplex':

            max_return.solve()
            # min_wcvar.solution.is_primal_feasible()

            if max_return.solution.is_primal_feasible():
                objective_value = max_return.solution.get_objective_value()
                indices = [max_return.variables.get_names().index(i) for i in w0_asset_weights]
                w_0_values = [max_return.solution.get_values()[index] for index in indices]
                w_0_variables = w0_asset_weights

            else:
                print('Not primal feasible.')
                objective_value = np.nan
                w_0_values = np.nan
                w_0_variables = np.nan

        results[k] = objective_value

    if to_save == 'yes':
        print('Writing the LP to file.')

        if not os.path.exists(os.getcwd() + '/results/' + folder):
            os.makedirs(os.getcwd() + '/results/' + folder)

        max_return.write(os.getcwd() + "/results/" + folder + "/robust_optimisation_programme.lp")

    # Get the optimal value of returns
    max_scenario = max(results, key=results.get)
    print('Maximum return is %0.3f (from scenario %s).' % (results[max_scenario], max_scenario))

    return results

#
#
# # Get returns for all scenarios
# k_returns = {}
# for k in scenarios_dict:
#     print(k)
#
#     # print(k)
#     return_constraint_variables = []
#     return_constraint_parameters = []
#
#     for node in final_nodes:
#         # print(node)
#         return_constraint_variables.append(
#             ['w_k' + str(k) + "_" + instrument + "_s" + str(node)[:-1] for instrument in instruments])
#         return_constraint_parameters.append(
#             np.array(scenarios_dict[str(k)][scenarios_dict[str(k)]['node'] == str(node)].T[2:-1].T.astype(float) \
#                      * float(
#                 scenarios_dict[str(k)][scenarios_dict[str(k)]['node'] == str(node)]['cum_probability'])).flatten())
#
#     # Flatten the lists
#     return_constraint_variables = [item for sublist in return_constraint_variables for item in sublist]
#     return_constraint_parameters = [item for sublist in return_constraint_parameters for item in sublist]
#
#     # Put to dataframe and then group by weight (sum it)
#     # Define the dataframe to be populated
#     data_dict = {'variables': return_constraint_variables, 'values': return_constraint_parameters}
#     data_df = pd.DataFrame(data=data_dict)
#     data_grouped = data_df.groupby(['variables'])['values'].sum()
#     return_constraint_variables = data_grouped.index
#     return_constraint_parameters = data_grouped.values
#
#     # Get the variable values in the end
#     print('Getting indices')
#     indices = [min_wcvar.variables.get_names().index(i) for i in return_constraint_variables]
#     print('Getting values')
#     values = [min_wcvar.solution.get_values()[index] for index in indices]
#
#     # Get return
#     k_returns[k] = np.sum(return_constraint_parameters * values)
#
# # Same things, but for CVaR
# wcvar_dict = {}
# for k in scenarios_dict:
#
#     # print(k)
#     wcvar_constraint_variables = ['var_' + str(k),
#                                   *["z_k" + str(k) + "_s" + str(node) for node in final_nodes]]
#     z_parameters = scenarios_dict[str(k)][scenarios_dict[str(k)]['node'].isin(final_nodes)]['cum_probability'].astype(float)
#     z_parameters = np.array(z_parameters) * (-1/(1-beta))
#     wcvar_contraint_parameters = [-1.0, *z_parameters]
#
#     # Get the variable values in the end
#     print('Getting indices')
#     wcvar_indices = [min_wcvar.variables.get_names().index(i) for i in wcvar_constraint_variables]
#     print('Getting values')
#     wcvar_values = [min_wcvar.solution.get_values()[index] for index in wcvar_indices]
#
#     # Get wcvars
#     wcvar_dict[k] = -np.sum(np.array(wcvar_contraint_parameters) * np.array(wcvar_values))
#
#     # Get the scenario with minimum CVaR
#     min(wcvar_dict, key=wcvar_dict.get)
#


# print('Adding period t = T return constraints.')
# for k in scenarios_dict:
#     # print(k)
#     return_constraint_variables = []
#     return_constraint_parameters = []
#
#     for node in final_nodes:
#         # print(node)
#         return_constraint_variables.append(
#             ['w_k' + str(k) + "_" + instrument + "_s" + str(node)[:-1] for instrument in instruments])
#         return_constraint_parameters.append(
#             np.array(scenarios_dict[str(k)][scenarios_dict[str(k)]['node'] == str(node)].T[2:-1].T.astype(float) \
#                      * float(
#                 scenarios_dict[str(k)][scenarios_dict[str(k)]['node'] == str(node)]['cum_probability'])).flatten())
#
#     # Flatten the lists
#     return_constraint_variables = [item for sublist in return_constraint_variables for item in sublist]
#     return_constraint_parameters = [item for sublist in return_constraint_parameters for item in sublist]
#
#     # Put to dataframe and then group by weight (sum it)
#     # Define the dataframe to be populated
#     data_dict = {'variables': return_constraint_variables, 'values': return_constraint_parameters}
#     data_df = pd.DataFrame(data=data_dict)
#     data_grouped = data_df.groupby(['variables'])['values'].sum()
#     return_constraint_variables = data_grouped.index
#     return_constraint_parameters = data_grouped.values

#
# # Implementation of simple CVaR optimiser
# def cvar_optimiser(data, scenarios, scenarios_cum, instruments, branching, return_target=0.0003594170240829454,
#                    beta=0.95):
#
#     # Simple VAR minimisation with scenario trees (using only the end of the scenarios, not intermediate results)
#     min_var = cplex.Cplex()
#
#     # Set as minimisation problem
#     min_var.objective.set_sense(min_var.objective.sense.minimize)
#
#     #### VARIABLES ####
#
#     # Define variables - weights for all assets, z variable for all scenarios and alpha (VaR)
#     alpha = 'alpha'
#     nr_scenarios = reduce(mul, branching, 1)
#     z = ["z_"+str(i) for i in range(nr_scenarios)]
#     assets = ["x_"+str(i) for i in instruments]
#     variables = list([alpha, *z, *assets])
#
#     # Set bounds
#     lower_bounds = np.repeat(0.0, len(variables))
#
#     # # Add alpha
#     # min_var.variables.add(names=['alpha'])
#     #
#     # # Add z's
#     # min_var.variables.add(names= ["z"+str(i) for i in range(output.shape[0])])
#     #
#     # # Add asset weights
#     # min_var.variables.add(names= instruments)
#
#     #### OBJECTIVE FUNCTION ####
#     probabilities = np.array(scenarios[instruments[1]]['probability'])*(1/(1-beta))
#     asset_weights = np.repeat(0., len(assets))
#     c = list([1, *probabilities, *asset_weights])
#
#     # Define variables and objective function
#     min_var.variables.add(lb = lower_bounds,
#                           names = variables,
#                           obj = c)
#
#     # for i in range(num_decision_var):
#     #     min_var.objective.set_linear([(i, c[i])])
#
#     #### CONSTRAINTS ####
#
#     # Add budget (weight) constraint
#     weight_constraint_parameters = list([*np.repeat(1.0, len(asset_weights))])
#     min_var.linear_constraints.add(lin_expr = [cplex.SparsePair(ind= assets, val= weight_constraint_parameters)],
#                                    senses = ["E"],
#                                    rhs = [1.0],
#                                    names = ['weight_constraint'])
#
#     # Add minimum return threshold
#     # Get the percentage change
#     stock_data_pc = data/data.shift(1)-1
#     means = list(stock_data_pc.mean())
#     instrument_variables = ["x_"+str(i) for i in instruments]
#     min_var.linear_constraints.add(lin_expr = [cplex.SparsePair(ind= instrument_variables, val= means)],
#                                    senses = ["G"],
#                                    rhs = [return_target],
#                                    names = ['return_target'])
#
#     #  CVaR needs to exceed VaR
#     # Iterate over scenarios and construct constraint for each scenario
#     for i in range(nr_scenarios):
#         # print(i)
#
#         returns = []
#         # Get loss for each instrument
#         for instrument in instruments:
#             # print(instrument)
#             loss = scenarios_cum[instrument].iloc[-1, :] / scenarios_cum[instrument].iloc[0, :] - 1
#             returns.append(loss[i])
#
#         losses = np.array(returns) * -1
#         instrument_variables = ["x_" + str(i) for i in instruments]
#         variable_index = ["z_" + str(i), *instrument_variables, alpha]
#         coefficients = [1, *(losses), 1]
#
#         # Add constraint
#         min_var.linear_constraints.add(
#             lin_expr= [cplex.SparsePair(ind= variable_index, val= coefficients)],
#             rhs= [0],
#             names = ["scenario_" + str(i)],
#             senses = ["G"])
#
#
#     # Run the solver
#     min_var.solve()
#     # min_var.variables.get_names()
#     # print(min_var.solution.get_values())
#
#     # Calculate CVaR
#     CVaR = np.sum(np.array(c) * np.array(min_var.solution.get_values()))
#
#     return CVaR, min_var.solution.get_values(), c, min_var
#
#
# def robust_cvar_optimiser(forecast_scenarios, instruments, branching, initial_portfolio,
#                           sell_bounds, buy_bounds, weight_bounds, cost_to_buy=0.01, cost_to_sell=0.01,
#                           beta=0.95, initial_wealth=1, return_target=0.000359):
#
#     # Initialise the object
#     min_wcvar = cplex.Cplex()
#
#     # Set as minimisation problem
#     min_wcvar.objective.set_sense(min_wcvar.objective.sense.minimize)
#
#     # Get quantities required to define variables
#     nr_trees = branching[0] # K variable in the model
#     nr_time_periods = len(branching)+1  # Includes first time period (t=0)
#     nr_scenarios = reduce(mul, branching[1:], 1) # S variable in the model
#
#     #### VARIABLES ####
#
#     # Define variables - weights for all assets, z variable for all scenarios and var
#     wcvar = 'wcvar'
#     var = 'var'
#
#     # For period t=0 (same for all scenarios)
#     w0_asset_weights = ["w_t0_" + str(j) for j in instruments]
#     w0_asset_buys = ["b_t0_" + str(j) for j in instruments]
#     w0_asset_sells = ["s_t0_" + str(j) for j in instruments]
#     # w0_all_variables = [*w0_asset_weights, *w0_asset_buys, *w0_asset_sells]
#
#     # For periods t= 1, ..., T-1
#     z = ["z_k" + str(i) + "_s" + str(j) for i in range(nr_trees) for j in range(nr_scenarios)] #
#     asset_weights = ["w_k" + str(k) + "_" + str(i) + "_t" + str(t) + "_s" +str(s)  for k in range(nr_trees) for i in instruments for t in range(1, nr_time_periods-1) for s in range(nr_scenarios)]
#     asset_buys = ["b_k" + str(k) + "_" + str(i) + "_t" + str(t) + "_s" +str(s)  for k in range(nr_trees) for i in instruments for t in range(1, nr_time_periods-1) for s in range(nr_scenarios)]
#     asset_sells = ["s_k" + str(k) + "_" + str(i) + "_t" + str(t) + "_s" +str(s)  for k in range(nr_trees) for i in instruments for t in range(1, nr_time_periods-1) for s in range(nr_scenarios)]
#     all_variables = list([wcvar, var, *z, *w0_asset_weights, *asset_weights,
#                           *w0_asset_buys, *asset_buys, *w0_asset_sells, *asset_sells])
#
#     # Set bounds for variables
#     wcvar_bounds = [[0.0], [cplex.infinity]]
#     var_bounds = [[0.0], [cplex.infinity]]
#     z_bounds = [np.repeat(0.0,len(z)), np.repeat(1e20, len(z))]
#     all_lower_bounds = list([*wcvar_bounds[0], *var_bounds[0], *z_bounds[0],
#                              *weight_bounds[0], *buy_bounds[0], *sell_bounds[0]])
#     all_upper_bounds = list([*wcvar_bounds[1], *var_bounds[1], *z_bounds[1],
#                              *weight_bounds[1], *buy_bounds[1], *sell_bounds[1]])
#
#     #### OBJECTIVE FUNCTION ####
#     objective_function = list([1.0, *np.repeat(0.0, len(all_variables)-1)])
#
#     # Define variables and objective function
#     min_wcvar.variables.add(names=all_variables,
#                             obj=objective_function,
#                             lb=all_lower_bounds,
#                             ub=all_upper_bounds)
#
#     #### CONSTRAINTS ####
#
#     ### Period t=0 constraints
#     # For each asset a separate row is needed for t=0 weight
#     for i, j in zip(instruments, range(len(instruments))): # j is to loop over the initial_portfolio list
#         # print(i, j)
#         asset = 'w_t0_' + i
#         to_buy = 'b_t0_' + i
#         to_sell = 's_t0_' + i
#         w_0_variables = [asset, to_buy, to_sell]
#         w_0_values = [1.0, -(1.0-cost_to_buy), 1.0+cost_to_sell]
#         min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=w_0_variables, val=w_0_values)],
#                                          senses=["E"],
#                                          rhs=[initial_portfolio[j]],
#                                          names=[asset])
#
#     # Normalise weights to 1 at t=0
#     w0_asset_buys = ["b_t0" + "_" + str(j) for j in instruments]
#     w0_asset_sells = ["s_t0" + "_" + str(j) for j in instruments]
#     w_0_variables = [*w0_asset_buys, *w0_asset_sells]
#     w_0_values = [*np.repeat(1.0, len(w0_asset_buys)), *np.repeat(-1.0, len(w0_asset_sells))]
#     min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=w_0_variables, val=w_0_values)],
#                                      senses=["E"],
#                                      rhs=[1.0-np.sum(initial_portfolio)],
#                                      names=["w_0_balance_constraint"])
#
#     ### Constraints for the intermediate periods t = 1, ...., T-1
#     # Weights constraint, taking into account the return
#     for k in range(nr_trees):
#         for instrument in instruments:
#             for t in range(1, nr_time_periods - 1):
#                 for s in range(nr_scenarios):
#                     # print(s)
#
#                     return_constraint_variables = []
#
#                     # Take the weight from previous period
#                     if t == 1: # Takes the 0th period weight
#                         # print(t)
#                         return_constraint_variables.append('w_t0_'+instrument)
#
#                     else:
#                         return_constraint_variables.append('w_k' + str(k) + "_" + instrument + "_t" + str(t-1) + "_s" + str(s))
#
#                     # Take the buys and sells from current period
#                     return_constraint_variables.append('b_k' + str(k) + "_" + instrument + "_t" + str(t) + "_s" + str(s))
#                     return_constraint_variables.append('s_k' + str(k) + "_" + instrument + "_t" + str(t) + "_s" + str(s))
#
#                     # Deduct the current rating (to have right side 0)
#                     return_constraint_variables.append('w_k' + str(k) + "_" + instrument + "_t" + str(t) + "_s" + str(s))
#
#                     # Get the parameters
#                     return_constraint_parameters = [0.0, 1.0-cost_to_buy, -(1.0+cost_to_sell), -1.0]
#                     return_constraint_parameters[0] = forecast_scenarios[str(k)][instrument][t][s]
#
#                     # Set constraints
#                     min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=return_constraint_variables, val=return_constraint_parameters)],
#                                                      senses=["E"],
#                                                      rhs=[0.0],
#                                                      names=[return_constraint_variables[-1] + "_return_constraint"])
#
#     # Buy-sell balance constraints
#     for k in range(nr_trees):
#         for t in range(1, nr_time_periods - 1):
#             for s in range(nr_scenarios):
#
#                 asset_buys = ['b_k' + str(k) + "_" + instrument + "_t" + str(t) + "_s" + str(s) for instrument in instruments]
#                 asset_sells = ['s_k' + str(k) + "_" + instrument + "_t" + str(t) + "_s" + str(s) for instrument in instruments]
#                 balance_constraint_variables = [*asset_buys, *asset_sells]
#                 balance_constraint_parameters = [*np.repeat(1.0, len(asset_buys)), *np.repeat(-1.0, len(asset_sells))]
#
#                 # Set the constraints
#                 min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=balance_constraint_variables, val=balance_constraint_parameters)],
#                                                  senses=["E"],
#                                                  rhs=[0.0],
#                                                  names=['k' + str(k) + "_t" + str(t) + "_s" + str(s) + "_balance_constraint"])
#
#     # WCVAR constraints for each scenario
#     for k in range(nr_trees):
#         # print(k)
#
#         wcvar_constraint_variables =  ['wcvar', 'var',  *["z_k" + str(k) + "_s" + str(s) for s in range(nr_scenarios)]]
#         z_parameters = forecast_scenarios[str(k)][instruments[0]]['probability'] / np.sum(forecast_scenarios[str(k)][instruments[0]]['probability'])
#         z_parameters = np.array(z_parameters) * (-1/(1-beta))
#         wcvar_contraint_parameters = [1, -1, *z_parameters]
#
#         min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=wcvar_constraint_variables, val=wcvar_contraint_parameters)],
#                                          senses=["G"],
#                                          rhs=[0.0],
#                                          names=["wcvar_constraint"])
#
#     # z constraint for each scenario
#     for k in range(nr_trees):
#         for s in range(nr_scenarios):
#
#             z = "z_k" + str(k) + "_s" + str(s)
#             z_constraint_variables = [z]
#             z_constraint_parameters = [1.0]
#
#             for instrument in instruments:
#
#                 z_constraint_variables.append(*['w_k' + str(k) + "_" + instrument + "_t" + str(nr_time_periods - 2) + "_s" + str(s)])
#                 z_constraint_parameters.append(*[(forecast_scenarios[str(k)][instrument][s:s+1][nr_time_periods - 1][0])*initial_wealth]) # Deduct 1 to get return and multiply by initial wealth W_0
#
#             z_constraint_variables.append(*['var'])
#             z_constraint_parameters.append(*[1.0])
#
#             min_wcvar.linear_constraints.add(
#                 lin_expr=[cplex.SparsePair(ind=wcvar_constraint_variables, val=wcvar_contraint_parameters)],
#                 senses=["G"],
#                 rhs=[initial_wealth],
#                 names=[z + "_constraint"])
#
#     # Return constraint for period t = T
#     for k in range(nr_trees):
#         return_constraint_variables = []
#         return_constraint_parameters = []
#
#         for s in range(nr_scenarios):
#             for instrument in instruments:
#                 return_constraint_variables.append(*['w_k' + str(k) + "_" + instrument + "_t" + str(nr_time_periods - 2) + "_s" + str(s)])
#                 return_constraint_parameters.append(*[(forecast_scenarios[str(k)][instrument][s:s+1][nr_time_periods - 1][0])*
#                                                                forecast_scenarios[str(k)][instrument][s:s + 1]['probability'][0]/
#                                                       np.sum(forecast_scenarios[str(k)][instrument]['probability'])])
#
#         # Set constraint such that the return is over certain threshold
#         min_wcvar.linear_constraints.add(lin_expr=[cplex.SparsePair(ind=return_constraint_variables, val=return_constraint_parameters)],
#                                          senses=["G"],
#                                          rhs=[return_target],
#                                          names=['k' + str(k) + "_t" + str(nr_time_periods - 1) + "_s" + str(s) + "_return_constraint"])
#
#     # Run the solver
#     min_wcvar.solve()
#     # min_wcvar.variables.get_names()
#     # print(min_wcvar.solution.get_values())
#
#     return min_wcvar
#



# Implementation of the robust multi-stage CVaR optimisation program
# Define the programme:
#
# Minimize the maximum conditional Value at Risk (CVaR) with the following constraints:
#
#     1. Transaction constraint - asset weight equals initial weight minus sold plus bought (and costs deducted)
#     2. Capital allocation - at time t=0, the initial budget should be normalised to 1.
#     3. Balance constraints - transactions should not alter the wealth within the period
#     4. Expected risk - expected



#
#
# # myProblem.variables.add(names= ["x"+str(i) for i in range(num_decision_var)])
#
# # Input all the data and parameters here
# num_decision_var = 3
# num_constraints = 3
#
# A = [
#     [1.0, -2.0, 1.0],
#     [-4.0, 1.0, 2.0],
#     [-2.0, 0, 1.0],
# ]
# b = [11.0, 3.0, 1.0]
# c = [-3.0, 1.0, 1.0]
#
# constraint_type = ["L", "G", "E"] # Less, Greater, Equal
# # ============================================================
#
# # Establish the Linear Programming Model
#
# # Add the decision variables and set their lower bound and upper bound (if necessary)
# myProblem.variables.add(names= ["x"+str(i) for i in range(num_decision_var)])
# for i in range(num_decision_var):
#     myProblem.variables.set_lower_bounds(i, 0.0)
#
# # Add constraints
# for i in range(num_constraints):
#     myProblem.linear_constraints.add(
#         lin_expr= [cplex.SparsePair(ind= [j for j in range(num_decision_var)], val= A[i])],
#         rhs= [b[i]],
#         names = ["c"+str(i)],
#         senses = [constraint_type[i]]
#     )
#
# # Add objective function and set its sense
# for i in range(num_decision_var):
#     myProblem.objective.set_linear([(i, c[i])])
# myProblem.objective.set_sense(myProblem.objective.sense.minimize)
#
# # Solve the model and print the answer
# myProblem.solve()
# print(myProblem.solution.get_values())



# Define objective function - minimise alpa + sum of zs product with probabilities
# Define constraints





# # Test
#
#
# import cplex
#
# # Create an instance of a linear problem to solve
# problem = cplex.Cplex()
#
#
# # We want to find a maximum of our objective function
# problem.objective.set_sense(problem.objective.sense.maximize)
#
# # The names of our variables
# names = ["x", "y", "z"]
#
# # The obective function. More precisely, the coefficients of the objective
# # function. Note that we are casting to floats.
# objective = [5.0, 2.0, -1.0]
#
# # Lower bounds. Since these are all zero, we could simply not pass them in as
# # all zeroes is the default.
# lower_bounds = [0.0, 0.0, 0.0]
#
# # Upper bounds. The default here would be cplex.infinity, or 1e+20.
# upper_bounds = [100, 1000, cplex.infinity]
#
# problem.variables.add(obj = objective,
#                       lb = lower_bounds,
#                       ub = upper_bounds,
#                       names = names)
#
# # Constraints
#
# # Constraints are entered in two parts, as a left hand part and a right hand
# # part. Most times, these will be represented as matrices in your problem. In
# # our case, we have "3x + y - z ≤ 75" and "3x + 4y + 4z ≤ 160" which we can
# # write as matrices as follows:
#
# # [  3   1  -1 ]   [ x ]   [  75 ]
# # [  3   4   4 ]   [ y ] ≤ [ 160 ]
# #                  [ z ]
#
# # First, we name the constraints
# constraint_names = ["c1", "c2"]
#
# # The actual constraints are now added. Each constraint is actually a list
# # consisting of two objects, each of which are themselves lists. The first list
# # represents each of the variables in the constraint, and the second list is the
# # coefficient of the respective variable. Data is entered in this way as the
# # constraints matrix is often sparse.
#
# # The first constraint is entered by referring to each variable by its name
# # (which we defined earlier). This then represents "3x + y - z"
# first_constraint = [["x", "y", "z"], [3.0, 1.0, -1.0]]
# # In this second constraint, we refer to the variables by their indices. Since
# # "x" was the first variable we added, "y" the second and "z" the third, this
# # then represents 3x + 4y + 4z
# second_constraint = [[0, 1, 2], [3.0, 4.0, 4.0]]
# constraints = [ first_constraint, second_constraint ]
#
# # So far we haven't added a right hand side, so we do that now. Note that the
# # first entry in this list corresponds to the first constraint, and so-on.
# rhs = [75.0, 160.0]
#
# # We need to enter the senses of the constraints. That is, we need to tell Cplex
# # whether each constrains should be treated as an upper-limit (≤, denoted "L"
# # for less-than), a lower limit (≥, denoted "G" for greater than) or an equality
# # (=, denoted "E" for equality)
# constraint_senses = [ "L", "L" ]
#
# # Note that we can actually set senses as a string. That is, we could also use
# #     constraint_senses = "LL"
# # to pass in our constraints
#
# # And add the constraints
# problem.linear_constraints.add(lin_expr = constraints,
#                                senses = constraint_senses,
#                                rhs = rhs,
#                                names = constraint_names)
#
# # Solve the problem
# problem.solve()
#
# # And print the solutions
# print(problem.solution.get_values())
#
#
#
#
# ###################################
#
# # Create an instance of a linear problem to solve
# problem = cplex.Cplex()
#
#
# # We want to find a maximum of our objective function
# problem.objective.set_sense(problem.objective.sense.maximize)
#
# # The names of our variables
# names = ["x", "y", "z"]
# objective = [5.0, 2.0, -1.0]
# lower_bounds = [0.0, 0.0, 0.0]
# upper_bounds = [100, 1000, cplex.infinity]
#
# problem.variables.add(obj = objective,
#                       lb = lower_bounds,
#                       ub = upper_bounds,
#                       names = names)
#
# constraint_names = ["c1", "c2"]
#
# first_constraint = [["x", "y", "z"], [3.0, 1.0, -1.0]]
#
# second_constraint = [[0, 1, 2], [3.0, 4.0, 4.0]]
# constraints = [ first_constraint, second_constraint ]
# rhs = [75.0, 160.0]
#
# # We need to enter the senses of the constraints. That is, we need to tell Cplex
# # whether each constrains should be treated as an upper-limit (≤, denoted "L"
# # for less-than), a lower limit (≥, denoted "G" for greater than) or an equality
# # (=, denoted "E" for equality)
# constraint_senses = [ "L", "L" ]
#
# # And add the constraints
# problem.linear_constraints.add(lin_expr = constraints,
#                                senses = constraint_senses,
#                                rhs = rhs,
#                                names = constraint_names)
#
# # Solve the problem
# problem.solve()
#
# # And print the solutions
# print(problem.solution.get_values())
#
# ##################################
#
# # ============================================================
# # This file gives us a sample to use Cplex Python API to
# # establish a Linear Programming model and then solve it.
# # The Linear Programming problem displayed bellow is as:
# #                  min z = cx
# #    subject to:      Ax = b
# # ============================================================
#
# # ============================================================
# # Input all the data and parameters here
# num_decision_var = 3
# num_constraints = 3
#
# A = [
#     [1.0, -2.0, 1.0],
#     [-4.0, 1.0, 2.0],
#     [-2.0, 0, 1.0],
# ]
# b = [11.0, 3.0, 1.0]
# c = [-3.0, 1.0, 1.0]
#
# constraint_type = ["L", "G", "E"] # Less, Greater, Equal
# # ============================================================
#
# # Establish the Linear Programming Model
# myProblem = cplex.Cplex()
#
# # Add the decision variables and set their lower bound and upper bound (if necessary)
# myProblem.variables.add(names= ["x"+str(i) for i in range(num_decision_var)])
# for i in range(num_decision_var):
#     myProblem.variables.set_lower_bounds(i, 0.0)
#
# # Add constraints
# for i in range(num_constraints):
#     myProblem.linear_constraints.add(
#         lin_expr= [cplex.SparsePair(ind= [j for j in range(num_decision_var)], val= A[i])],
#         rhs= [b[i]],
#         names = ["c"+str(i)],
#         senses = [constraint_type[i]]
#     )
#
# # Add objective function and set its sense
# for i in range(num_decision_var):
#     myProblem.objective.set_linear([(i, c[i])])
# myProblem.objective.set_sense(myProblem.objective.sense.minimize)
#
# # Solve the model and print the answer
# myProblem.solve()
# print(myProblem.solution.get_values())
#
#
#
#
#
# ############# GUROBI EXAMPLE ######################
#
#
# #!/usr/bin/python
#
# # Copyright 2018, Gurobi Optimization, LLC
#
# # Portfolio selection: given a sum of money to invest, one must decide how to
# # spend it amongst a portfolio of financial securities.  Our approach is due
# # to Markowitz (1959) and looks to minimize the risk associated with the
# # investment while realizing a target expected return.  By varying the target,
# # one can compute an 'efficient frontier', which defines the optimal portfolio
# # for a given expected return.
# #
# # Note that this example reads historical return data from a comma-separated
# # file (../data/portfolio.csv).  As a result, it must be run from the Gurobi
# # examples/python directory.
# #
# # This example requires the pandas, NumPy, and Matplotlib Python packages,
# # which are part of the SciPy ecosystem for mathematics, science, and
# # engineering (http://scipy.org).  These packages aren't included in all
# # Python distributions, but are included by default with Anaconda Python.
#
# from gurobipy import *
# from math import sqrt
# import pandas as pd
# import numpy as np
# import matplotlib.pyplot as plt
#
# # Import (normalized) historical return data using pandas
# data = stock_data.pct_change(1)
# stocks = data.columns
#
# # Calculate basic summary statistics for individual stocks
# stock_volatility = data.std()
# stock_return = data.mean()
#
# # Create an empty model
# m = Model('portfolio')
#
# # Add a variable for each stock
# vars = pd.Series(m.addVars(stocks), index=stocks)
#
# # Objective is to minimize risk (squared).  This is modeled using the
# # covariance matrix, which measures the historical correlation between stocks.
# sigma = data.cov()
# portfolio_risk = sigma.dot(vars).dot(vars)
# m.setObjective(portfolio_risk, GRB.MINIMIZE)
#
# # Fix budget with a constraint
# m.addConstr(vars.sum() == 1, 'budget')
#
# # Optimize model to find the minimum risk portfolio
# m.setParam('OutputFlag', 0)
# m.optimize()
#
# # Create an expression representing the expected return for the portfolio
# portfolio_return = stock_return.dot(vars)
#
# # Display minimum risk portfolio
# print('Minimum Risk Portfolio:\n')
# for v in vars:
#     if v.x > 0:
#         print('\t%s\t: %g' % (v.varname, v.x))
# minrisk_volatility = sqrt(portfolio_risk.getValue())
# print('\nVolatility      = %g' % minrisk_volatility)
# minrisk_return = portfolio_return.getValue()
# print('Expected Return = %g' % minrisk_return)
#
# # Add (redundant) target return constraint
# target = m.addConstr(portfolio_return == minrisk_return, 'target')
#
# # Solve for efficient frontier by varying target return
# frontier = pd.Series()
# for r in np.linspace(stock_return.min(), stock_return.max(), 100):
#     target.rhs = r
#     m.optimize()
#     frontier.loc[sqrt(portfolio_risk.getValue())] = r
#
# # Plot volatility versus expected return for individual stocks
# ax = plt.gca()
# ax.scatter(x=stock_volatility, y=stock_return,
#            color='Blue', label='Individual Stocks')
# for i, stock in enumerate(stocks):
#     ax.annotate(stock, (stock_volatility[i], stock_return[i]))
#
# # Plot volatility versus expected return for minimum risk portfolio
# ax.scatter(x=minrisk_volatility, y=minrisk_return, color='DarkGreen')
# ax.annotate('Minimum\nRisk\nPortfolio', (minrisk_volatility, minrisk_return),
#             horizontalalignment='right')
#
# # Plot efficient frontier
# frontier.plot(color='DarkGreen', label='Efficient Frontier', ax=ax)
#
# # Format and display the final plot
# ax.axis([0.005, 0.06, -0.02, 0.025])
# ax.set_xlabel('Volatility (standard deviation)')
# ax.set_ylabel('Expected Return')
# ax.legend()
# ax.grid()
# plt.show()
