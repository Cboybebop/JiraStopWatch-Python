# JiraStopWatch-Python
Python app that logs time against Jira tickets based on users tracked time.

## Getting Started

1. Install the dependencies using your preferred Python environment (Python 3.10+).

   ```bash
   pip install -r requirements.txt
   ```

2. Launch the desktop application:

   ```bash
   python -m jirastopwatch
   ```

3. Open **File → Settings** and provide your Jira Cloud base URL, email address and API token. Once saved, you can test the connection via **File → Test Connection**.

## Track Multiple Jira Issues
![alt text](https://www.jirastopwatch.com/img/screen1.png)
Quickly add/remove as many time-tracking slots you want available.
Time is reported in Jira time-logging format (eg. 2h 31m).
Jira issue keys are saved on program exit - including time tracking state.

## Easy issue Selection
![alt text](https://www.jirastopwatch.com/img/screen2.png)
Switch between all your favorite JQL filters.
Select issue keys from list of available issues, based on JQL filter,
or simply copy/paste Jira urls to automatically extract issue key.

## Easy worklog posting
![alt text](https://www.jirastopwatch.com/img/screen3.png)
Posting spent time into Jira as a worklog with comment.
Worklog comments can be saved with timestamp for later posting.
Control remaining estimates.

## Integration with Jira
Jira authentication to use API tokens
Select issue keys from a list based on one of your favorite JQL filters, type it, or copy/paste a URL from Jira.
Displays issue description when key has been added.
Post spent time into Jira as a worklog with comments - and either let Jira automatically update remaining estimate, or set it yourself.
Automatically set Jira issue "In progress" when pressing play on a timer.


## Easy time tracking of Jira issues
Switch time tracking between issues with just one click.
Quickly add/remove as many time-tracking slots you want available.
Time can be manually edited (eg. if you forgot to start the timer when starting work). Just double-click on the time field.
Optionally pause timer when locking your PC.

## Automatically save program state on exit
Jira API tokens saved on program exit. 
Jira issue keys are saved on program exit.
Optionally save time-tracking state, so your stopwatch continue to "run" even if you need to quit the program (e.g. you need to reboot, but still want to keep on recording time.