"""
/*
 * @Author: ThaumicMekanism [Stephan K.] 
 * @Date: 2020-01-23 20:57:36 
 * @Last Modified by: ThaumicMekanism [Stephan K.]
 * @Last Modified time: 2020-04-25 14:56:44
 */
"""
"""
This is the base of the autograder.
"""
import json
import time
import datetime
import os
from .AutograderTest import AutograderTest, global_tests, Max
from .AutograderErrors import AutograderSafeEnvError, AutograderHalt
from .AutograderSetup import global_setups
from .AutograderTeardown import global_teardowns
from .Utils import root_dir, submission_dir, results_path, get_welcome_message, is_local, WhenToRun, submission_metadata_dir

printed_welcome_message = False

class RateLimit:
    def __init__(
        self,
        tokens:int=None,
        seconds:int=0,
        minutes:int=0,
        hours:int=0,
        days:int=0,
        reset_time:str=None,
        pull_prev_run=False,
        submission_id_exclude=[]
    ):
        self.tokens = tokens
        self.seconds = seconds
        self.minutes = minutes
        self.hours = hours
        self.days = days
        self.reset_time = reset_time
        self.output = ""

        self.pull_prev_run = pull_prev_run

        self.submission_id_exclude = submission_id_exclude

        self.oldest_token_time = None
        self.current_submission_time = None

        self.main_string = ""
        self.tokens_used = ""

    def print(self, *args, sep=' ', end='\n', file=None, flush=True, also_stdout=False):
        msg = sep.join(map(str, args)) + end
        if also_stdout:
            print(msg)
        self.output += msg

    def set_next_token_regen(self, oldest_token_time, current_submission_time):
        self.oldest_token_time = oldest_token_time
        self.current_submission_time = current_submission_time

    def rate_limit_set_main_string(self, string, tokens_used):
        self.main_string = string
        self.tokens_used = tokens_used

    def get_rate_limit_str(self, ag: "Autograder"):
        datetime_regen_rate = datetime.timedelta(seconds=self.total_seconds())
        sub_to_count = None
        if self.oldest_token_time:
            sub_to_count = self.oldest_token_time
        else:
            if ag.rate_limit_does_submission_count():
                sub_to_count = self.current_submission_time
        

        tu = self.tokens_used
        if not ag.rate_limit_does_submission_count():
            tu -= 1

        if sub_to_count is not None:
            next_token_regen = sub_to_count + datetime_regen_rate
            next_token_regen_str = f"[Rate Limit]: As of this submission time, your next token will regenerate at {next_token_regen.ctime()} (PT).\n\n"
        else:
            next_token_regen_str = "[Rate Limit]: As of this submission time, you have not used any tokens!\n\n"

        return self.main_string.format(tu) + next_token_regen_str

    def total_seconds(self):
        return self.seconds + 60 * (self.minutes + 60 * (self.hours + (24 * self.days)))

class Autograder:
    use_ratelimit_when_local = False

    def __init__(self, rate_limit=None, reverse_tests=False, export_tests_after_test=True, modify_results=lambda results: results):
        self.tests = []
        self.setups = []
        self.teardowns = []
        self.results_file = results_path()
        self.score = None
        self.output = None
        self.visibility = None
        self.stdout_visibility = None
        self.extra_data = {}
        self.leaderboard = None
        self.reverse_tests = reverse_tests
        self.export_tests_after_test = export_tests_after_test
        # rate_limit takes in a RateLimit class.
        # reset_time is when you want to reset the submission time. You
        # can leave it out to ignore. Put the time stirng in this format:
        #  "2018-11-29T16:15:00"
        self.rate_limit:RateLimit = rate_limit
        self.start_time = datetime.datetime.now()
        self.modify_results = modify_results

        if not is_local():
            with open(submission_metadata_dir(), "r") as jsonMetadata:
                self.metadata = json.load(jsonMetadata)
            self.extra_data["id"] = self.metadata["id"]
        else:
            if os.path.isfile(submission_metadata_dir()):
                with open(submission_metadata_dir(), "r") as jsonMetadata:
                    self.metadata = json.load(jsonMetadata)
                self.extra_data["id"] = self.metadata["id"]
            else:
                self.extra_data["id"] = "LOCAL"
                self.metadata = None

    @staticmethod
    def run(ag = None):
        global printed_welcome_message
        if not printed_welcome_message:
            printed_welcome_message = True
            print(get_welcome_message())
        def f(ag):
            for t in global_tests:
                ag.add_test(t)
            for s in global_setups:
                ag.add_setup(s)
            for t in global_teardowns:
                ag.add_teardown(t)
            ag.execute()
        Autograder.main(f, ag=ag)

    @staticmethod
    def main(f, ag=None):
        global printed_welcome_message
        if not printed_welcome_message:
            printed_welcome_message = True
            print(get_welcome_message())
        if ag is None:
            ag = Autograder()
        def handler(exception):
            ag.ag_fail("An exception occured in the autograder's main function. Please contact a TA to resolve this issue.")
            return True
        def wrapper():
            f(ag)
        ag.safe_env(wrapper, handler)

    def dump_results(self, data: dict) -> None:
        jsondata = json.dumps(data, ensure_ascii=False)
        with open(self.results_file, "wb") as f:
            f.write(jsondata.encode("unicode-escape"))

    def add_test(self, test, index=None):
        if isinstance(test, AutograderTest):
            if index is None:
                self.tests.append(test)
            else:
                self.tests.insert(index, test)
            return
        raise ValueError("You must add type Test to the autograder.")

    def add_setup(self, setupfn):
        self.setups.append(setupfn)

    def add_teardown(self, teardownfn):
        self.teardowns.append(teardownfn)

    def set_score(self, score):
        self.score = score
    
    def add_score(self, addition):
        if self.score is None:
            self.score = 0
        self.score += addition
    
    def get_score(self):
        score = None
        for test in self.tests:
            test_score = test.get_score()
            if test_score is not None:
                if score is None:
                    score = test_score
                else:
                    score += test_score
        if score is None:
            score = self.score
        return score

    def print(self, *args, sep=' ', end='\n', file=None, flush=True):
        if self.output is None:
            self.output = ""
        self.output += sep.join(map(str, args)) + end

    def create_test(self, *args, **kwargs):
        test = AutograderTest(*args, **kwargs)
        self.add_test(test)

    def ag_fail(self, message: str, extra: dict={}, exit_prog=True) -> None:
        data = {
            "score": 0,
            "output": message
        }
        data.update(extra)
        self.dump_results(data)
        if exit_prog:
            import sys
            sys.exit()
    
    def safe_env(self, f, handler=None):
        try:
            return f()
        except Exception as exc:
            print("An exception occured in the safe environment!")
            import traceback
            traceback.print_exc()
            print(exc)
            if handler is not None:
                try:
                    h = handler(exc)
                    if h:
                        return AutograderSafeEnvError(h)
                except Exception as exc:
                    print("An exception occurred while executing the exception handler!")
                    traceback.print_exc()
            self.ag_fail("An unexpected exception ocurred while trying to execute the autograder. Please try again or contact a TA if this persists.")
            return AutograderSafeEnvError(exc)

    def run_tests(self):
        global printed_welcome_message
        if not printed_welcome_message:
            printed_welcome_message = True
            print(get_welcome_message())
        local = is_local()
        def handle_failed():
                self.set_score(0)
                if "sub_counts" in self.extra_data:
                    self.print("[Rate Limit]: Since the autograder failed to run, you will not use up a token!")
                    self.rate_limit_unset_submission()
        for setup in self.setups:
            if not setup.when_to_run.okay_to_run(local):
                continue
            res = setup.run(self)
            if not res:
                print(f"[Error]: ({setup.name}) Returned non-true value `{res}` so assuming it failed!")
                self.print("[Error]: An error occurred in the setup of the Autograder!")
                handle_failed()
                return False
        for test in self.tests:
            test.run(self)
            if self.export_tests_after_test:
                self.generate_results(print_main_score_warning_error=False)
        for teardown in self.teardowns:
            if not teardown.when_to_run.okay_to_run(local):
                continue
            res = teardown.run(self)
            if not res:
                print(f"[Error]: ({teardown.name}) Returned non-true value `{res}` so assuming it failed!")
                self.print("[Error]: An error occurred in the teardown of the Autograder!")
                handle_failed()
                return False
        return True

    def generate_results(self, test_results=None, leaderboard=None, dump=True, print_main_score_warning_error=True):
        results = {
            "execution_time": (datetime.datetime.now() - self.start_time).total_seconds(),
        }
        if test_results is None:
            tests = []
            if self.reverse_tests:
                tsts = reversed(self.tests)
            else:
                tsts = self.tests
            for test in tsts:
                res = test.get_results()
                if res:
                    tests.append(res)
            if tests:
                results["tests"] = tests
        else:
            if isinstance(test_results, list):
                results["tests"] = test_results
        if self.score is not None:
            results["score"] = self.score
        else:
            if "tests" not in results or len(results["tests"]) == 0 or not any(["score" in t for t in results["tests"]]):
                results["score"] = 0
                if print_main_score_warning_error:
                    self.print("This autograder does not set the main score or have any tests which give points!")
        if self.output is not None:
            results["output"] = self.output
        if self.visibility is not None:
            results["visibility"] = self.visibility
        if self.stdout_visibility is not None:
            results["stdout_visibility"] = self.stdout_visibility
        if self.extra_data:
            results["extra_data"] = self.extra_data
        if leaderboard:
            results["leaderboard"] = leaderboard
        else:
            if self.leaderboard is not None:
                results["leaderboard"] = self.leaderboard
        results = self.modify_results(results)
        if dump:
            self.dump_results(results)
        return results
        
    def execute(self):
        global printed_welcome_message
        if not printed_welcome_message:
            printed_welcome_message = True
            print(get_welcome_message())
        self.rate_limit_main()
        if not self.run_tests():
            print("An error has occurred when attempting to run all tests.")
        if isinstance(self.rate_limit, RateLimit):
            if self.output is None:
                self.output = ""
            self.output = self.rate_limit.get_rate_limit_str(self) + self.output
        self.generate_results()

    @staticmethod
    def root_dir() -> str:
        return root_dir()

    @staticmethod
    def submission_dir() -> str:
        return submission_dir()

    def add_leaderboard_item(self, name: str, value: any, order: str=None):
        if self.leaderboard is None:
            self.leaderboard = []
        for item in self.leaderboard:
            if item["name"] == name:
                item["value"] = value
                if order is not None:
                    item["order"] = order
                break
        else:
            item = {
                "name": name,
                "value": value
            }
            if order is not None:
                item["order"] = order
            self.leaderboard.append(item)
    
    def get_leaderboard_item(self, name: str):
        for item in self.leaderboard:
            if item["name"] == name:
                return item
        return None
    
    def remove_leaderboard_item(self, name: str):
        item = self.get_leaderboard_item(name)
        if item:
            self.leaderboard.remove(item)
            return True
        return False
    
    def rate_limit_main(self, verbose=False):
        if is_local() and not self.use_ratelimit_when_local:
            print("[WARNING]: Rate limit is enabled but will not be checked because this has been detected to be a local run!")
            return
        if isinstance(self.rate_limit, RateLimit) and self.rate_limit.tokens is not None:
            tokens = self.rate_limit.tokens
            restart_subm_string = self.rate_limit.reset_time
            s = self.rate_limit.seconds
            m = self.rate_limit.minutes
            h = self.rate_limit.hours
            d = self.rate_limit.days
            regen_time_seconds = self.rate_limit.total_seconds()
            def get_submission_time(s):
                return s[:-13]
            def pretty_time_str(s, m, h, d):
                sstr = "" if s == 0 else str(s) + " second"
                sstr += "" if sstr == "" or s == 1 else "s"
                mstr = "" if m == 0 else str(m) + " minute"
                mstr += "" if mstr == "" or m == 1 else "s"
                hstr = "" if h == 0 else str(h) + " hour"
                hstr += "" if hstr == "" or h == 1 else "s"
                dstr = "" if d == 0 else str(d) + " day"
                dstr += "" if dstr == "" or d == 1 else "s"
                st = dstr
                for tmpstr in [hstr, mstr, sstr]:
                    if st != "" and tmpstr != "":
                        st += " "
                    st += tmpstr
                if st == "":
                    st = "none"
                return st
            current_subm_string = get_submission_time(self.metadata["created_at"])
            current_time = time.strptime(current_subm_string,"%Y-%m-%dT%H:%M:%S")
            restart_time = time.strptime(restart_subm_string, "%Y-%m-%dT%H:%M:%S") if restart_subm_string is not None else None
            tokens_used = 0
            if verbose:
                print("=" * 30)
            oldest_counted_submission = None
            for i, v in enumerate(self.metadata["previous_submissions"]):
                subm_string = get_submission_time(v["submission_time"])
                subm_time = time.strptime(subm_string,"%Y-%m-%dT%H:%M:%S")
                if restart_time is not None and time.mktime(subm_time) - time.mktime(restart_time) < 0:
                    if verbose:
                        print("Ignoring a submission, too early!")
                    continue
                if verbose:
                    print("Current time: " + str(time.mktime(current_time)))
                    print("Subm time: " + str(time.mktime(subm_time)))
                if (time.mktime(current_time) - time.mktime(subm_time) < regen_time_seconds): 
                    try:
                        if verbose:
                            print(self.metadata["previous_submissions"][i])
                            print("Tokens used: " + str(tokens_used))
                            print(str(self.metadata["previous_submissions"][i].keys()))
                            print("Current submission data: " + str(self.metadata["previous_submissions"][i]["results"]["extra_data"]))
                        ed = self.metadata["previous_submissions"][i]["results"]["extra_data"]
                        if ed is not None:
                            subID = ed.get("id")
                            if (ed["sub_counts"] == 1) and (subID and (subID not in self.rate_limit.submission_id_exclude)): 
                                if oldest_counted_submission is None:
                                    oldest_counted_submission = subm_time
                                tokens_used = tokens_used + 1
                        else:
                            if verbose:
                                print(f"Extra data not available in previous submission {i}!")
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        print(e)
                        tokens_used = tokens_used + 1
                        pass
                if verbose:
                    print("-" * 30)
            if verbose:
                print("=" * 30)
            datetime_regen_rate = datetime.timedelta(seconds=regen_time_seconds)
            if oldest_counted_submission:
                oldest_counted_submission = datetime.datetime.fromtimestamp(time.mktime(oldest_counted_submission))
            if current_time:
                datetime_current_time = datetime.datetime.fromtimestamp(time.mktime(current_time))
            if tokens_used < tokens:
                self.extra_data["sub_counts"] = 1
                tokens_used += 1 # This is to include the current submission.
                self.rate_limit.rate_limit_set_main_string(f"[Rate Limit]: Students can get up to {tokens} graded submissions within any given period of {pretty_time_str(s, m, h, d)}. In the last period, you have had {{}} graded submissions.\n", tokens_used)
                self.rate_limit.set_next_token_regen(oldest_counted_submission, datetime_current_time)
            else:
                self.extra_data["sub_counts"] = 0
                if self.rate_limit.pull_prev_run:
                    msg = ", so the results of your last graded submission are being displayed."
                else:
                    msg = "."
                self.print(f"[Rate Limit]: Students can get up to {tokens} graded submissions within any given period of {pretty_time_str(s, m, h, d)}. You have already had {tokens_used} graded submissions within the last {pretty_time_str(s, m, h, d)}{msg} Because you do not have any more tokens, this submission will not count as a graded submission.")

                if oldest_counted_submission:
                    next_token_regen = oldest_counted_submission + datetime_regen_rate
                    self.print(f"[Rate Limit]: As of this submission time, your next token will regenerate at {next_token_regen.ctime()} (PT).\n")
                else:
                    self.print(f"[Rate Limit]: As of this submisison, you have not used any tokens.\n")
                
                if self.rate_limit.pull_prev_run:
                    prev_subs = self.metadata["previous_submissions"]
                    prev_sub = prev_subs[len(prev_subs) - 1]
                    if prev_sub and "results" not in prev_sub or prev_sub["results"] and "tests" not in prev_sub["results"]:
                        self.print("[ERROR]: Could not pull the data from your previous submission! This is probably due to it not have finished running!")
                        tests = []
                        self.set_score(0)
                        leaderboard = None
                    else:
                        res = prev_sub["results"]
                        tests = res["tests"]
                        leaderboard = res["leaderboard"]
                        self.set_score(prev_sub.get("score"))
                else:
                        tests = []
                        self.set_score(0)
                        leaderboard = None
                    
                self.generate_results(test_results=tests, leaderboard=leaderboard)
                
                import sys
                sys.exit()
                # raise AutograderHalt("Rate limited!")

    def rate_limit_unset_submission(self):
        self.extra_data["sub_counts"] = 0

    def rate_limit_does_submission_count(self):
        return self.extra_data["sub_counts"]

    @staticmethod
    def DUMP(msg):
        ag = Autograder()
        ag.print(msg)
        ag.set_score(0)
        ag.generate_results()