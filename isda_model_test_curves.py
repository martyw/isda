from datetime import datetime
import ctypes
import math
from dataclasses import dataclass
from dataclasses import KW_ONLY
import unittest

import isda.c_interface

date_format = "%d/%m/%Y"

@dataclass
class CurvePoint:
    _: KW_ONLY
    value_date: datetime
    tenor: datetime
    
    @property
    def year_fraction(self):
        return (self.tenor - self.value_date).days/365.0

@dataclass
class CreditCurvePoint(CurvePoint):
    _: KW_ONLY
    survival_propability: float

    def __str__(self):
        return ",".join([self.tenor.strftime(date_format)] + [str(x) for x in (self.survival_propability, self.year_fraction)])

@dataclass
class IRCurvePoint(CurvePoint):
    _: KW_ONLY
    discount_factor: float

    @property
    def zero_rate(self):
        return (-1.0*math.log(self.discount_factor))/self.year_fraction

    def __str__(self):
        return ",".join([self.tenor.strftime(date_format)] + [str(x) for x in (self.discount_factor, self.year_fraction, self.zero_rate)])

class Curve:
    def __init__(self, value_date, object_name, tenors, bad_day_convention, holidays):
        self.isda_dll = isda.c_interface.CInterface()
        self.object_name = object_name
        self.value_date = value_date
        self.tenors = tenors
        self.value_date_jpmfmt = self.isda_dll.JpmcdsDate(self.value_date.year, self.value_date.month, self.value_date.day)
        if bad_day_convention not in ("N", "M", "F"):
            raise ValueError(f"Bad Bad Day Convention {bad_day_convention}, expected N, M, or F")
        self.bad_day_convention = ord(bad_day_convention)
        self.holidays = holidays
        self.result_curve = []
        
    def daycount_convention(self, daycount_code):
        tp = (ctypes.c_long * 1)()
        self.isda_dll.JpmcdsStringToDayCountConv(daycount_code, tp)
        
        return ctypes.c_long(tp[0])

    def convert_to_interval(self, term):
        interval = isda.c_interface.TDateInterval()
        self.isda_dll.JpmcdsStringToDateInterval(term, self.object_name, interval)

        return interval
        
    def forward_date_calculation(self, term):
        interval = self.convert_to_interval(term)
        dt = (ctypes.c_int * 1)()
        self.isda_dll.JpmcdsDateFwdThenAdjust(self.value_date_jpmfmt, interval, self.bad_day_convention, self.holidays, dt)
        
        return dt[0]
        
    def write_to_file(self, file_name):
        with open (file_name, "w") as f:
            f.write(str(self))
            
    def get_tenor_and_value(self, crv, i):
        _tenor = crv[0].fArray[i].fDate
        tenor = datetime.strptime("".join([chr(j) for j in list(self.isda_dll.JpmcdsFormatDate(_tenor))]), "%Y%m%d")
        curve_value = self.isda_dll.JpmcdsZeroPrice(crv, _tenor)

        return (tenor, curve_value)

class CreditCurve(Curve):
    def __init__(self, value_date, tenors, zero_curve, accrual_start_date, \
                pay_accrual_on_default, coupon_interval, stub_type, payment_dcc, bad_day_convention, holidays, \
                recovery_rate, cds_spreads):
        Curve.__init__(self, value_date, "CDSSpreadCurve", tenors, bad_day_convention, holidays)
        self.zero_curve = zero_curve[0]
        self.stepin_date = self.forward_date_calculation("1D")
        self.cash_settle_date = self.forward_date_calculation("3D")
        self.cds_spreads = (ctypes.c_double * len(cds_spreads))(*cds_spreads)
        self.recovery_rate = recovery_rate
        self.pay_accrual_on_default = pay_accrual_on_default
        self.coupon_interval = self.convert_to_interval(coupon_interval)
        self.payment_dcc = self.daycount_convention(payment_dcc)
        
        self.stubFS = isda.c_interface.TStubMethod(False, False)
        _ = self.isda_dll.JpmcdsStringToStubMethod(stub_type, ctypes.byref(self.stubFS))

    def build(self):
        # tenors
        jpm_imm_dates = [self.isda_dll.JpmcdsDate(dt.year, dt.month,dt.day) for (_, dt) in self.tenors]
        tenors = (ctypes.c_int * len(jpm_imm_dates))(*jpm_imm_dates)
        
        credit_curve = self.isda_dll.JpmcdsCleanSpreadCurve(self.value_date_jpmfmt, self.zero_curve, \
                                self.value_date_jpmfmt, self.stepin_date, self.cash_settle_date, len(jpm_imm_dates),\
                                tenors, self.cds_spreads, None, self.recovery_rate, self.pay_accrual_on_default, \
                                self.coupon_interval, self.payment_dcc, self.stubFS, self.bad_day_convention, self.holidays)
        
        for i in range(credit_curve[0].fNumItems):
            (tenor, survival_propability) = self.get_tenor_and_value(credit_curve, i)
            self.result_curve.append(CreditCurvePoint(value_date = self.value_date, tenor = tenor, survival_propability = survival_propability))

    def __str__(self):
        return "tenor,YearFraction,survival propability\n" + "\n".join([str(pt) for pt in self.result_curve])

class IRZeroCurve(Curve):
    def __init__(self, value_date, instrument_types, tenors, rates, money_marketDCC, fixedleg_freq, floatleg_freq, fixedleg_dcc, floatleg_dcc, bad_day_convention, holidays):
        Curve.__init__(self,value_date, "BuildZeroCurve", tenors, bad_day_convention, holidays)
        self.instrument_types = "".join(instrument_types)
        self.rates = (ctypes.c_double * len(rates))(*rates)
        self.money_marketDCC = self.daycount_convention(money_marketDCC)
        self.fixedleg_freq = self.swapleg_frequency(fixedleg_freq)
        self.floatleg_freq = self.swapleg_frequency(floatleg_freq)
        self.fixedleg_dcc = self.daycount_convention(fixedleg_dcc)
        self.floatleg_dcc = self.daycount_convention(floatleg_dcc)
        
    def build(self):            
        # tenors
        tenor_dates = []
        for tenor in self.tenors:
            tenor_dates.append(self.forward_date_calculation(tenor))
        tenor_dates = (ctypes.c_int * len(tenor_dates))(*tenor_dates)
                
        zero_curve = self.isda_dll.JpmcdsBuildIRZeroCurve(self.value_date_jpmfmt, self.instrument_types, tenor_dates, self.rates, \
                                                            len(self.instrument_types), self.fixedleg_freq, self.floatleg_freq, \
                                                            self.money_marketDCC, self.fixedleg_dcc, self.floatleg_dcc, \
                                                            self.bad_day_convention, self.holidays)

        # add only points not on consecutive days
        for i in range(zero_curve[0].fNumItems):
            (tenor, discount_factor) = self.get_tenor_and_value(zero_curve, i)
            if i == 0:
                self.result_curve.append(IRCurvePoint(value_date = self.value_date, tenor = tenor, discount_factor = discount_factor))
            elif (tenor - self.result_curve[-1].tenor).days > 7:
                self.result_curve.append(IRCurvePoint(value_date = self.value_date, tenor = tenor, discount_factor = discount_factor))
            else:
                pass
                    
        return zero_curve
                
    def __str__(self):
        return "tenor,discount factor,YearFraction,Zero rate\n" + "\n".join([str(pt) for pt in self.result_curve])

    def swapleg_frequency(self, freq):
        tmp = isda.c_interface.TDateInterval()
        self.isda_dll.JpmcdsStringToDateInterval(freq, self.object_name, tmp)
        freq_p = (ctypes.c_double * 1)()
        self.isda_dll.JpmcdsDateIntervalToFreq(tmp, freq_p)
        
        return ctypes.c_long(int(freq_p[0]))

if __name__ == "__main__":    
    class TestCurveBuilders(unittest.TestCase):
        def setUp(self):
            # zero curve
            open_gamma_market_data_example = [("M", "1M", 0.00445), ("M", "2M", 0.00949), ("M", "3M", 0.01234),\
                ("M", "6M", 0.01776), ("M", "9M", 0.01935), ("M", "1Y", 0.02084), ("S", "2Y", 0.01652),\
                ("S", "3Y", 0.02018), ("S", "4Y", 0.02303), ("S", "5Y", 0.02525), ("S", "6Y", 0.02696),\
                ("S", "7Y", 0.02825), ("S", "8Y", 0.02931),("S", "9Y", 0.03017),("S", "10Y", 0.03092),\
                ("S", "11Y", 0.03160),("S", "12Y", 0.03231),("S", "15Y", 0.03367), ("S", "20Y", 0.03419),\
                ("S", "25Y", 0.03411),("S", "30Y", 0.03412)]

            instrument_types =  [tp for (tp, tenor, rate) in open_gamma_market_data_example]
            tenors =  [tenor for (tp, tenor, rate) in open_gamma_market_data_example]
            rates =  [rate for (tp, tenor, rate) in open_gamma_market_data_example]

            value_date = datetime.strptime("13/06/2011", date_format)
    
            self.zero_crv = IRZeroCurve(value_date, instrument_types, tenors, rates, "ACT/360", "6M", "3M", "30/360",  "ACT/360", "M", "None")
            zero_curve = self.zero_crv.build()
            self.zero_crv.write_to_file("zero_curve.csv")
            
            open_gamma_market_data_example = [("6M", "20/12/2011", 0.007927), ("1Y", "20/06/2012", 0.007927), \
                                              ("3Y", "20/06/2014", 0.012239), ("5Y", "20/06/2016", 0.016979), \
                                              ("7Y", "20/06/2018", 0.019271), ("10Y", "20/06/2021", 0.02086)]
            
            value_date = datetime.strptime("13/06/2011", date_format)
            accrual_start_date = datetime.strptime("20/03/2011", date_format)
            pay_accrual_on_default = True
            coupon_interval = "3M"
            stub_type = "F/S"
            payment_dcc = "ACT/360"
            bad_day_convention = "F"
            holiday = "None"
            recovery_rate = 0.4
            
            tenors = [(tenor, datetime.strptime(dt, date_format)) for (tenor, dt, _) in open_gamma_market_data_example]
            cds_spreads = [cds_spread for (_, _, cds_spread) in open_gamma_market_data_example]
            self.credit_crv = CreditCurve(value_date, tenors, zero_curve, accrual_start_date, pay_accrual_on_default, \
                                          coupon_interval, stub_type, payment_dcc, bad_day_convention, holiday, recovery_rate, cds_spreads)
            self.credit_crv.build()
            self.credit_crv.write_to_file("cds_curve.csv")
            
        def testIRCurveTenors(self):
            self.assertEqual(self.zero_crv.result_curve[1].tenor, datetime(2011, 7, 13))
            self.assertEqual(self.zero_crv.result_curve[2].tenor, datetime(2011, 8, 15))
            self.assertEqual(self.zero_crv.result_curve[3].tenor, datetime(2011, 9, 13))
            self.assertEqual(self.zero_crv.result_curve[4].tenor, datetime(2011, 12, 13))
            self.assertEqual(self.zero_crv.result_curve[5].tenor, datetime(2012, 3, 13))
            self.assertEqual(self.zero_crv.result_curve[6].tenor, datetime(2012, 6, 13))
            self.assertEqual(self.zero_crv.result_curve[7].tenor, datetime(2012, 12, 13))
            self.assertEqual(self.zero_crv.result_curve[8].tenor, datetime(2013, 6, 13))
            self.assertEqual(self.zero_crv.result_curve[9].tenor, datetime(2013, 12, 13))
            self.assertEqual(self.zero_crv.result_curve[10].tenor, datetime(2014, 6, 13))
            self.assertEqual(self.zero_crv.result_curve[11].tenor, datetime(2014, 12, 15))
            self.assertEqual(self.zero_crv.result_curve[12].tenor, datetime(2015, 6, 15))
            
            self.assertEqual(self.zero_crv.result_curve[64].tenor, datetime(2041, 6, 13))
               
            
        def testZeros(self):
            self.assertAlmostEqual(self.zero_crv.result_curve[1].zero_rate, 0.00451, 5)
            self.assertAlmostEqual(self.zero_crv.result_curve[2].zero_rate, 0.00961, 5)
            self.assertAlmostEqual(self.zero_crv.result_curve[3].zero_rate, 0.01249, 5)
            self.assertAlmostEqual(self.zero_crv.result_curve[4].zero_rate, 0.01793, 5)
            self.assertAlmostEqual(self.zero_crv.result_curve[5].zero_rate, 0.01948, 5)
            self.assertAlmostEqual(self.zero_crv.result_curve[6].zero_rate, 0.02091, 5)
            self.assertAlmostEqual(self.zero_crv.result_curve[7].zero_rate, 0.01790, 5)
            self.assertAlmostEqual(self.zero_crv.result_curve[8].zero_rate, 0.01640, 5)
            self.assertAlmostEqual(self.zero_crv.result_curve[9].zero_rate, 0.01863, 5)
            self.assertAlmostEqual(self.zero_crv.result_curve[10].zero_rate, 0.02011, 5)
            
            self.assertAlmostEqual(self.zero_crv.result_curve[64].zero_rate, 0.03441, 5)
            
        def testCreditCurveTenors(self):
            self.assertEqual(self.credit_crv.result_curve[0].tenor, datetime(2011, 12, 20))
            self.assertEqual(self.credit_crv.result_curve[1].tenor, datetime(2012, 6, 20))
            self.assertEqual(self.credit_crv.result_curve[2].tenor, datetime(2014, 6, 20))
            self.assertEqual(self.credit_crv.result_curve[3].tenor, datetime(2016, 6, 20))
            self.assertEqual(self.credit_crv.result_curve[4].tenor, datetime(2018, 6, 20))
            self.assertEqual(self.credit_crv.result_curve[5].tenor, datetime(2021, 6, 20))
        
        def testSurvivalProbabilities(self):
            self.assertAlmostEqual(self.credit_crv.result_curve[0].survival_propability, 0.99307, 5)
            self.assertAlmostEqual(self.credit_crv.result_curve[1].survival_propability, 0.98644, 5)
            self.assertAlmostEqual(self.credit_crv.result_curve[2].survival_propability, 0.93914, 5)
            self.assertAlmostEqual(self.credit_crv.result_curve[3].survival_propability, 0.86255, 5)
            self.assertAlmostEqual(self.credit_crv.result_curve[4].survival_propability, 0.78860, 5)
            self.assertAlmostEqual(self.credit_crv.result_curve[5].survival_propability, 0.69042, 5)
    
    unittest.main()
     
