"""Domain Port module for the ``candidate_pool`` bounded context.

The M4 ``CandidatePoolCalculator`` Protocol previously defined here has
been removed: only the PR-08 minimum calculator ships today, and its
:data:`invest_domain.candidate_pool.calculator.MinimumCandidatePoolCalculator`
Protocol already locks the call signature. The M4 Protocol will be
re-introduced here when the full algorithm lands.
"""
