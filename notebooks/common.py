# common.py
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import ticker
import matplotlib.dates as mdates

import pathlib
import requests
import bs4
import re
import statsmodels.api as sm
import os
from time import time
import datetime
import scipy.stats as stats
from io import StringIO

from typing import List


# --- WARNINGS ---

_warnings = []

def warn(message):
    print(message)
    _warnings.append(message)


def print_warnings():
    for i, w in enumerate(_warnings):
        print(f'{i+1:3d}: {w}')


def check_file_current(filename, message):
    file_status = os.stat(filename)
    modified_date = datetime.date(*time.localtime(file_status.st_mtime)[:3])
    today = datetime.date.today()
    if modified_date != today:
        warn(f'{filename}: File looks old. ' + message)

# --- WEB SCRAPING -=-

# --- [VERY SIMPLE] WEB BASED DATA CAPTURE --

def get_url(url: str) -> str:
    """Get the text at a URL."""
    
    headers = {
        "Cache-Control": "no-cache, must-revalidate, private, max-age=0",
        "Pragma": "no-cache",
    }
    response = requests.get(url.format(rn=time()), headers=headers)
    assert response.status_code == 200  # successful retrieval
    return response.text


def get_table_list(url: str) -> List[pd.DataFrame]:
    """Get a list of pandas DataFrames at a URL."""
    
    html = get_url(url)
    df_list = pd.read_html(StringIO(html))
    return df_list


# --- DATA CLEANING ---

# Common unicode symbols
endash = '\u2013'
emdash = '\u2014'
hyphen = '\u002D'
minus  = '\u2212'
tilde =  '~'
comma =  ','


def remove_event_rows(t: pd.DataFrame) -> pd.DataFrame:
    """Remove the event marker rows."""
    t = t.loc[t[t.columns[0]] != t[t.columns[1]]]
    t = t.loc[t[t.columns[1]] != t[t.columns[2]]]
    t = t[t[t.columns[1]].notna()]
    return t


def drop_empty(t: pd.DataFrame) -> pd.DataFrame:
    """Remove all empty rows and columns."""
    t = t.dropna(axis=0, how='all')
    t = t.dropna(axis=1, how='all')
    return t


def fix_numerical_cols(t: pd.DataFrame) -> pd.DataFrame:
    """Convert selected columns from strings to numeric data type."""
    
    # some constants
    fixable_cols = (
        # For the 2022 cycle
        'Primary vote', '2pp vote',
        'Preferred Prime Minister',
        'Morrison', 'Albanese',
        'Sample size', 
        # For historical cycles
        'TPP vote', '2PP vote', 
        'Political parties',
        'Two-party-preferred',
    )

    # navigate fixable columns and convert to numerical dtype
    for c in t.columns[t.columns.get_level_values(0).isin(fixable_cols)]:
        if str(t[c].dtype) in ['object', ]:
            t[c] = (
                t[c]
                .str.replace('\[.*\]$', '', regex=True) # remove footnotes
                .str.replace('%', '')    # remove percent symbol
                .str.replace(tilde, '')  # replace tilde with nothing
                .str.replace(hyphen, '') # replace hyphen with nothing
                .str.replace(endash, '') # replace hyphen with nothing
                .str.replace(emdash, '') # replace hyphen with nothing
                .str.replace(minus, '')  # replace hyphen with nothing
                .str.replace('n/a', '')  # replace 'n/a' with nothing
                .str.replace('?', '', regex=False)  # replace '?' with nothing
                .str.replace('<', '', regex=False)  # replace '<' with nothing
                .str.strip()             # strip white space
                .replace('', np.nan)     # NaN empty lines
                .astype(float)           # float
            )
    return t


def fix_column_names(t: pd.DataFrame) -> pd.DataFrame:
    """Replace 'Unnamed' column names with ''."""
    
    replacements = {}
    for c in t.columns:
        if 'Unnamed' in c[1]:
            replacements[c[1]] = ''
    if replacements:
        t = t.rename(columns=replacements, level=1)
    return t


def remove_footnotes(t: pd.DataFrame) -> pd.DataFrame:
    """Remove Wikipedia footnote references from the Brand column"""
    
    BRAND = ['Brand', 'Firm']
    
    for brand in BRAND:
        if brand not in t.columns.get_level_values(0):
            continue
        col = t.columns[t.columns.get_level_values(0) == brand]
        assert(len(col) == 1)
        t.loc[:, col] = (
            t.loc[:, col] # returns a single column DataFrame
            .pipe(lambda x: x[x.columns[0]]) # make as Series
            .str.replace('\[.*\]$', '', regex=True) # remove footnotes
            .str.strip() # remove any leading/trailing whitespaces
        )
    return t


def get_mean_date(tokens: List[str]) -> pd.Timestamp:
    """Extract the middle date from a list of date tokens."""

    last_day = None
    day, month, year = None, None, None
    remember = tokens.copy()
    while tokens:
        token = tokens.pop()

        if re.match(r"[0-9]{4}", token):
            year = token
        elif re.match(r"[A-Za-z]+", token):
            month = token
        elif re.match(r"[0-9]{1,2}", token):
            day = token
        else:
            print(
                f"WARNING: {token} not recognised in get_mean_date()"
                f"with these date tokens {remember}"
            )

        if (
            last_day is None
            and day is not None
            and month is not None
            and year is not None
        ):
            last_day = pd.Timestamp(f"{year} {month[:3]} {day}")

    if month is None:
        print(f"WARNING: missing month in these tokens? {remember}")

    # sadly we have cases of this ...
    if not last_day:
        if day is None:
            day = 1  # assume first of month
        last_day = pd.Timestamp(f"{year} {month[:3]} {day}")

    # get the middle date
    first_day = pd.Timestamp(f"{year} {month[:3]} {day}")
    if first_day > last_day:
        print(
            f"CHECK these dates in get_mean_date(): {first_day} "
            f"{last_day} with these tokens {remember}"
        )

    return (first_day + ((last_day - first_day) / 2)).date()


def tokenise_dates(dates: pd.Series) -> pd.Series:
    """Return the date as a list of tokens."""
    if type(dates) is pd.DataFrame:
        dates = dates[dates.columns[0]]  # WTF?

    return (
        dates.str.strip()
        .str.replace("\[.+\]", "", regex=True)  # footnotes
        .str.replace(endash, hyphen)
        .str.replace(emdash, hyphen)
        .str.replace(minus, hyphen)
        .str.replace("c. ", "", regex=False)
        .str.split(r"[\-,\s\/]+")
    )


def middle_date(t: pd.DataFrame) -> pd.DataFrame:
    """Get the middle date in the date range, into column 'Mean Date'."""

    # assumes dates in strings are ordered from first to last
    tokens = tokenise_dates(t["Date(s)"])
    t["Mean Date"] = tokens.apply(get_mean_date).astype("datetime64[ns]")
    return t
    

def clean(table: pd.DataFrame) -> pd.DataFrame:
    """Clean the extracted data tables."""
    
    t = table.copy()
    t = remove_event_rows(t)
    t = drop_empty(t)
    t = fix_numerical_cols(t)
    t = fix_column_names(t)
    t = remove_footnotes(t)
    t = middle_date(t)
    t = t.set_index(('Mean Date', ''))
    t = t.sort_index(ascending=True)
    # Note we keep the hierarchical index at this point
    # because it makes the checking row additions simpler
    
    return t


def flatten_col_names(columns: pd.Index) -> List[str]:
    """Flatten the hierarchical column index."""
    assert columns.nlevels >= 2
    return [' '.join(col).strip() if col[0] != col[1] else col[0] for col in columns.values]


# --- POLL AGGREGATION ---

# Calculate an exponentially weighted average
def calculate_ewm(series, times, halflife):
    """Calculate an exponentially weighted mean for a series."""
    
    # sanity checks
    assert len(series) == len(times)
    assert series.notna().all()
    assert times.notna().all()
    
    return (
        series
        .ewm(halflife=halflife, times=times)
        .mean()
    )


# Calulcate a LOWESS regression
def calculate_lowess(series, times, period):
    # sanity checks
    assert len(series) == len(times)

    day = (times - times.min()) / pd.Timedelta(days=1) + 1
    frac = period / day.max()
    if frac < 0 or frac > 1:
        return None
    
    lowess = sm.nonparametric.lowess(
        endog=series, exog=day, # y, x ...
        frac=frac, is_sorted=True)

    lowess = {int(x[0]): x[1] for x in lowess}
    lowess = day.map(lowess).interpolate()
    lowess.index = times

    return lowess


def calc_chi_squared(series, sample_sizes, percent=95, mean=None):
    
    # sanity checks
    assert percent >= 50 and percent <= 100 
    assert all(series >= 0) and all(series <= 100)  # series is percentages
    assert len(series) == len(sample_sizes)
    assert len(series) >= 2 

    # set up for calculation
    deg_of_freedom = len(series) - 1
    two_tail = ((100.0 - percent) / 100.0) / 2.0
    if mean is None:
        mean = series.mean()
    variances = (series * (100-series)) / sample_sizes
    standard_deviations = pd.Series(np.sqrt(variances))
    
    # Key calculations
    X = pow((series - mean)/standard_deviations, 2).sum()
    X_min = stats.distributions.chi2.ppf(two_tail, df=deg_of_freedom)
    X_max = stats.distributions.chi2.ppf(1 - two_tail, df=deg_of_freedom)
    
    # return results
    return (X, X_min, X_max, deg_of_freedom, percent)

# --- PLOTTING ---

COLOR_COALITION = 'darkblue'
COLOR_LABOR = '#dd0000'
COLOR_OTHER = 'darkorange'
COLOR_GREEN = 'darkgreen'

P_COLOR_COALITION = '#0000dd'
P_COLOR_LABOR = '#dd0000'
P_COLOR_OTHER = 'orange'
P_COLOR_GREEN = 'green'

MARKERS = [
    '$a$', '$b$', '$c$', '$d$', '$e$', 
    '$f$', '$g$', '$h$', '$i$', '$j$', 
    '$k$', '$l$', '$m$', '$n$', '$o$', 
    '$p$', '$q$', '$r$', '$s$', '$t$', 
    '$u$', '$v$', '$w$', '$x$', '$y$',
    '$z$',
]


def initiate_plot():
    """Get a matplotlib figure and axes instance."""
    fig, ax = plt.subplots(figsize=(9, 4.5), constrained_layout=False)
    ax.margins(0.02)
    return fig, ax


def plot_chi_square(X, X_min, X_max, dof, percent=None):
    x = np.linspace(0, X_min + X_max, 500)
    y = pd.Series(stats.chi2(dof).pdf(x), index=x)

    fig, ax = initiate_plot()
    y.plot(ax=ax)
    ax.axvline(X_min, color='royalblue')
    ax.axvline(X_max, color='royalblue')
    ax.axvline(X, color='darkorange')
    if percent is not None:
        ax.text(x=(X_min+X_max)/2, y=0.00, s=f'{percent}% between '+str(round(X_min, 2))+
            ' and '+str(round(X_max, 2)), ha='center', va='bottom')
    ax.text(x=X, y=y.max(), s='$\chi^2 = '+str(round(X, 2))+'$', 
        ha='right', va='top', rotation=90)
    
    return fig, ax


def annotate_endpoint(ax, series: pd.Series, end=None, rot=90):
    """Annotate the endpoint of a series on a plot."""
    xlim = ax.get_xlim() 
    span = xlim[1] - xlim[0]
    x = xlim[1] - 0.0075 * span # Based on 2% margins in initiate_plot()
    x = x if end is None else end
    font_size = 12 if rot == 90 else 10
    ax.text(x, series.iloc[-1], 
            f'{round(series.iloc[-1], 1)}',
            ha='left', va='center', rotation=rot, 
            fontsize=font_size)


def add_data_points_by_pollster(ax, df, column, p_color, 
                                brand_col='Firm', 
                                date_col='Mean Date', no_label=False, marker=None):
    """Add individual poll results to the plot."""
    for i, brand in enumerate(sorted(df[brand_col].unique())):
        poll = df[df[brand_col] == brand]
        series = (
            poll[column].sum(axis=1, skipna=True) if type(column) is list 
            else poll[column]
        )
        label = None if no_label else brand
        m = marker if marker is not None else MARKERS[i]
        ax.scatter(poll[date_col], series, marker=m, 
                   c=p_color, s=20, label=label)


def add_h_refence(ax, reference):
    """Add a horizontal reference line."""
    span = ax.get_ylim() 
    if span[0] <= reference <= span[1]:
        ax.axhline(y=reference, c='#999999', lw=0.5)


def add_summary_line(ax, df, column, l_color, function, argument, label=None, rot=0):
    """Add a line summary to the plot as calculated by function()"""
    series = df[column].sum(axis=1, skipna=True) if type(column) is list else df[column]
    times = df['Mean Date']
    summary = function(series, times, argument)
    if summary is not None:
        ax.plot(times, summary, lw=2.5, c=l_color, label=label)
        annotate_endpoint(ax, series=summary, end=times.iloc[-1]+pd.Timedelta(days=5), rot=rot)
    add_h_refence(ax, reference=50)


def plot_finalise(ax, title=None, xlabel=None, ylabel=None, 
                  lfooter=None, rfooter='marktheballot.blogspot.com',
                  location='../charts/', close=True, concise_dates=False,
                  straighten_tl=False, **kwargs):
    """Complete and save a plot image"""
    
    # annotate the plot
    if title is not None:
        ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    
    if lfooter is not None:
        ax.figure.text(0.005, 0.005, lfooter, 
                       ha='left', va='bottom',
                       c='#999999', style='italic', 
                       fontsize=9)

    if rfooter is not None:
        ax.figure.text(0.995, 0.005, rfooter, 
                       ha='right', va='bottom',
                       c='#999999', style='italic', 
                       fontsize=9)
        
    # format dates
    if concise_dates:
        locator = mdates.AutoDateLocator(minticks=4, maxticks=13)
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)

    # straigten tick labels
    if straighten_tl:
        for tick in ax.get_xticklabels():
            tick.set_rotation(0)
            tick.set_ha('center')
    
    ax.figure.tight_layout(pad=1.1)    
    
    if title is not None:
        replaceable = list(r'/\^:$')
        for char in replaceable:
            title = title.replace(char, '')
        file_stem = f'{location}{title}'
        if 'save_suffix' in kwargs:
            file_stem += '-' + kwargs['save_suffix']
        pathlib.Path(location).mkdir(parents=True, exist_ok=True)
        ax.figure.savefig(f'{file_stem}.png', dpi=300)
    
    # close
    if close:
        plt.show()
        plt.close()
    
    
def plot_summary_line(df, column, p_color, l_color, title,
                      function, argument, label, lfooter, rot=90):
    """Generate a summary line plot, where the line is generated by function()"""
    fig, ax = initiate_plot()
    add_data_points_by_pollster(ax, df, column, p_color)
    add_summary_line(ax, df, column, l_color, function, argument, label, rot=rot)
    ax.legend(loc='best')
    plot_finalise(ax, 
                     ylabel='Per cent',
                     title=title, 
                     lfooter=lfooter,
                     concise_dates=True)    
                     
                     
def plot_summary_line_by_pollster(df, column, title,
                                  function, argument, lfooter, rot=0):
    """For each pollster, plot a summary line calculated with function()"""
    MINIMUM_POLLS_REQUIRED = 2 # two polls needed for a line
    fig, ax = initiate_plot()
    for i, pollster in enumerate(sorted(df['Brand'].unique())):
        polls = df[df['Brand'] == pollster].copy()
        if len(polls) < MINIMUM_POLLS_REQUIRED:
            continue
        add_summary_line(ax, df=polls, column=column, l_color=None, 
                         function=function, argument=argument, rot=rot)
        add_data_points_by_pollster(ax, df=polls, column=column, p_color=None, marker=MARKERS[i])

    ax.legend(loc='best')
    plot_finalise(ax, 
                  ylabel='Per cent',
                  title=title, 
                  lfooter=lfooter,
                  concise_dates=True)
