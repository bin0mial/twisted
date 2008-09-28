# Copyright (c) 2001-2006 Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Test the interaction between trial and errors logged during test run.
"""

import time

from twisted.internet import reactor, defer, task
from twisted.python import failure, log, reflect
from twisted.trial import unittest, reporter, runner


def makeFailure():
    """
    Return a new, realistic failure.
    """
    try:
        1/0
    except ZeroDivisionError:
        f = failure.Failure()
    return f


class Mask(object):
    """
    Hide C{MockTest}s from Trial's automatic test finder.
    """

    class MockTest(unittest.TestCase):
        def test_silent(self):
            """
            Don't log any errors.
            """

        def test_single(self):
            """
            Log a single error.
            """
            log.err(makeFailure())

        def test_double(self):
            """
            Log two errors.
            """
            log.err(makeFailure())
            log.err(makeFailure())

        def test_inCallback(self):
            """
            Log an error in an asynchronous callback.
            """
            return task.deferLater(reactor, 0, lambda: log.err(makeFailure()))


class TestObserver(unittest.TestCase):
    """
    Tests for L{unittest._LogObserver}, a helper for the implementation of
    L{TestCase.flushLoggedErrors}, L{TestCase.flushWarnings}, and related
    functions.
    """
    def setUp(self):
        self.result = reporter.TestResult()
        self.observer = unittest._LogObserver()


    def test_msg(self):
        """
        Test that a standard log message doesn't go anywhere near the result.
        """
        self.observer.gotEvent({'message': ('some message',),
                                'time': time.time(), 'isError': 0,
                                'system': '-'})
        self.assertEqual(self.observer.getErrors(), [])


    def test_error(self):
        """
        Test that an observed error gets added to the result
        """
        f = makeFailure()
        self.observer.gotEvent({'message': (),
                                'time': time.time(), 'isError': 1,
                                'system': '-', 'failure': f,
                                'why': None})
        self.assertEqual(self.observer.getErrors(), [f])


    def test_flush(self):
        """
        Check that flushing the observer with no args removes all errors.
        """
        self.test_error()
        flushed = self.observer.flushErrors()
        self.assertEqual(self.observer.getErrors(), [])
        self.assertEqual(len(flushed), 1)
        self.assertTrue(flushed[0].check(ZeroDivisionError))


    def _makeRuntimeFailure(self):
        return failure.Failure(RuntimeError('test error'))


    def test_flushByType(self):
        """
        Check that flushing the observer remove all failures of the given type.
        """
        self.test_error() # log a ZeroDivisionError to the observer
        f = self._makeRuntimeFailure()
        self.observer.gotEvent(dict(message=(), time=time.time(), isError=1,
                                    system='-', failure=f, why=None))
        flushed = self.observer.flushErrors(ZeroDivisionError)
        self.assertEqual(self.observer.getErrors(), [f])
        self.assertEqual(len(flushed), 1)
        self.assertTrue(flushed[0].check(ZeroDivisionError))


    def test_ignoreErrors(self):
        """
        Check that C{_ignoreErrors} actually causes errors to be ignored.
        """
        self.observer._ignoreErrors(ZeroDivisionError)
        f = makeFailure()
        self.observer.gotEvent({'message': (),
                                'time': time.time(), 'isError': 1,
                                'system': '-', 'failure': f,
                                'why': None})
        self.assertEqual(self.observer.getErrors(), [])


    def test_clearIgnores(self):
        """
        Check that C{_clearIgnores} ensures that previously ignored errors
        get captured.
        """
        self.observer._ignoreErrors(ZeroDivisionError)
        self.observer._clearIgnores()
        f = makeFailure()
        self.observer.gotEvent({'message': (),
                                'time': time.time(), 'isError': 1,
                                'system': '-', 'failure': f,
                                'why': None})
        self.assertEqual(self.observer.getErrors(), [f])


    def test_flushWarnings(self):
        """
        Check that C{flushWarnings} returns a list of all warnings received by
        the observer and removes them from the observer.
        """
        here = self.test_flushWarnings.im_func.func_code
        filename = here.co_filename
        lineno = here.co_firstlineno
        event = {
            'warning': RuntimeWarning('some warning text'),
            'category': reflect.qual(RuntimeWarning),
            'filename': filename,
            'lineno': lineno,
            'format': 'bar'}
        # Make a copy to be sure no accidental sharing goes on.
        self.observer.gotEvent(dict(event))

        event['args'] = ('some warning text',)
        event['category'] = RuntimeWarning

        self.assertEqual(self.observer.flushWarnings(), [event])
        self.assertEqual(self.observer.flushWarnings(), [])


    def test_flushWarningsByFunction(self):
        """
        Check that C{flushWarnings} accepts a list of function objects and only
        returns warnings which refer to one of those functions as the offender.
        """
        def offenderOne():
            pass

        def offenderTwo():
            pass

        def nonOffender():
            pass

        # Emit a warning from the two offenders, but not from the non-offender.
        events = []
        for offender in [offenderOne, offenderTwo]:
            where = offender.func_code
            filename = where.co_filename
            lineno = where.co_firstlineno
            event = {
                'warning': RuntimeWarning('some warning text'),
                'category': reflect.qual(RuntimeWarning),
                'filename': filename,
                'lineno': lineno,
                'format': 'bar'}
            events.append(event)
            self.observer.gotEvent(dict(event))
            event['args'] = ('some warning text',)
            event['category'] = RuntimeWarning

        self.assertEqual(
            self.observer.flushWarnings([nonOffender]),
            [])
        self.assertEqual(
            self.observer.flushWarnings([offenderTwo]),
            events[1:])
        self.assertEqual(
            self.observer.flushWarnings([offenderOne]),
            events[:1])



class LogErrors(unittest.TestCase):
    """
    High-level tests demonstrating the expected behaviour of logged errors
    during tests.
    """

    def setUp(self):
        self.result = reporter.TestResult()

    def tearDown(self):
        self.flushLoggedErrors(ZeroDivisionError)

    def test_singleError(self):
        """
        Test that a logged error gets reported as a test error.
        """
        test = Mask.MockTest('test_single')
        test(self.result)
        self.assertEqual(len(self.result.errors), 1)
        self.assertTrue(self.result.errors[0][1].check(ZeroDivisionError),
                        self.result.errors[0][1])

    def test_twoErrors(self):
        """
        Test that when two errors get logged, they both get reported as test
        errors.
        """
        test = Mask.MockTest('test_double')
        test(self.result)
        self.assertEqual(len(self.result.errors), 2)

    def test_inCallback(self):
        """
        Test that errors logged in callbacks get reported as test errors.
        """
        test = Mask.MockTest('test_inCallback')
        test(self.result)
        self.assertEqual(len(self.result.errors), 1)
        self.assertTrue(self.result.errors[0][1].check(ZeroDivisionError),
                        self.result.errors[0][1])

    def test_errorsIsolated(self):
        """
        Check that an error logged in one test doesn't fail the next test.
        """
        t1 = Mask.MockTest('test_single')
        t2 = Mask.MockTest('test_silent')
        t1(self.result)
        t2(self.result)
        self.assertEqual(len(self.result.errors), 1)
        self.assertEqual(self.result.errors[0][0], t1)
