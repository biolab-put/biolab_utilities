import numpy as np
from scipy import stats
import pandas as pd

__all__ = ["n_way_anova"]


def n_way_anova(df_f, groups_column, score_column):
    factors = np.unique(df_f[groups_column])
    print(factors)
    results = pd.DataFrame(columns=factors, index=factors)
    for i in range(0, len(factors)):
        for j in range(i , len(factors)):
            factor_x = factors[i]
            factor_y = factors[j]

            # F, p = stats.f_oneway(df_f.loc[(df_f[groups_column] == factor_x)][score_column],
            #                       df_f.loc[(df_f[groups_column] == factor_y)][score_column])
            F, p = stats.ttest_ind(df_f.loc[(df_f[groups_column] == factor_x)][score_column],
                                  df_f.loc[(df_f[groups_column] == factor_y)][score_column])
            results.loc[factor_x][factor_y] = p
            results.loc[factor_y][factor_x] = p

    return results
