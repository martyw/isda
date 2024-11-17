from datetime import datetime
import ctypes
import math
from dataclasses import dataclass
import unittest

import isda.c_interface

@dataclass
class IRCurvePoint:
    value_date: datetime
    tenor: datetime
    discount_factor: float
    
    @property
    def year_fraction(self):
        return (self.tenor - self.value_date).days/365.0
    
    @property
    def zero_rate(self):
        return (-1.0*math.log(self.discount_factor))/self.year_fraction
            
    def __str__(self):
        return ",".join([self.tenor.strftime("%m/%d/%Y")] + [str(x) for x in (self.discount_factor, self.year_fraction, self.zero_rate)])

class IRZeroCurve:
    def __init__(self, value_date, instrument_types, tenors, rates, money_marketDCC, fixedleg_freq, floatleg_freq, fixedleg_dcc, floatleg_dcc, badDayConvention, holidays):
        self.isda_dll = isda.c_interface.CInterface()
        self.object_name = "BuildZeroCurve"
        self.value_date = value_date
        self.instrument_types = "".join(instrument_types)
        self.tenors = tenors
        self.rates = (ctypes.c_double * len(rates))(*rates)
        self.money_marketDCC = self.daycount_convention(money_marketDCC)
        self.fixedleg_freq = self.swapleg_frequency(fixedleg_freq)
        self.floatleg_freq = self.swapleg_frequency(floatleg_freq)
        self.fixedleg_dcc = self.daycount_convention(fixedleg_dcc)
        self.floatleg_dcc = self.daycount_convention(floatleg_dcc)
        self.badDayConvention = ord(badDayConvention)
        self.holidays = holidays
        
    def build(self):            
        valuation_date = self.isda_dll.JpmcdsDate(self.value_date.year, self.value_date.month, self.value_date.day)        
        # tenors
        tenor_dates = []
        for tenor in self.tenors:
            tmp = isda.c_interface.TDateInterval()
            self.isda_dll.JpmcdsStringToDateInterval(tenor, self.object_name, tmp)
            dt = (ctypes.c_int * 1)()
            self.isda_dll.JpmcdsDateFwdThenAdjust(valuation_date, tmp, self.badDayConvention, self.holidays, dt)
            tenor_dates.append(dt[0])
        tenor_dates = (ctypes.c_int * len(tenor_dates))(*tenor_dates)
                
        zero_curve = self.isda_dll.JpmcdsBuildIRZeroCurve(valuation_date, self.instrument_types, tenor_dates, self.rates, \
                                                            len(self.instrument_types), self.fixedleg_freq, self.floatleg_freq, \
                                                            self.money_marketDCC, self.fixedleg_dcc, self.floatleg_dcc, \
                                                            self.badDayConvention, self.holidays)

        self.result_curve = []
        # add only points not on consecutive days
        for i in range(zero_curve[0].fNumItems):
            _dt = zero_curve[0].fArray[i].fDate
            dt = datetime.strptime("".join([chr(i) for i in list(self.isda_dll.JpmcdsFormatDate(_dt))]), "%Y%m%d")
            if i == 0:
                self.add_point(_dt, dt, zero_curve)
            else:
                if (dt - self.result_curve[-1].tenor).days > 7:
                    self.add_point(_dt, dt, zero_curve)
                
    def __str__(self):
        return "tenor,discount factor,YearFraction,Zero rate\n" + "\n".join([str(pt) for pt in self.result_curve])

    def add_point(self, _tenor, tenor, zero_crv):
        discount_factor = self.isda_dll.JpmcdsZeroPrice(zero_crv, _tenor)          
        point = IRCurvePoint(self.value_date, tenor, discount_factor)
        self.result_curve.append(point)
    
    def daycount_convention(self, daycount_code):    
        tp = (ctypes.c_long * 1)()
        self.isda_dll.JpmcdsStringToDayCountConv(daycount_code, tp)
        
        return ctypes.c_long(tp[0])
        
    def swapleg_frequency(self, freq):
        tmp = isda.c_interface.TDateInterval()
        self.isda_dll.JpmcdsStringToDateInterval(freq, self.object_name, tmp)
        freq_p = (ctypes.c_double * 1)()
        self.isda_dll.JpmcdsDateIntervalToFreq(tmp, freq_p)
        
        return ctypes.c_long(int(freq_p[0]))
        
    
if __name__ == "__main__":    
    class TestIRCurveBuilder(unittest.TestCase):
        def setUp(self):
            open_gamma_market_data_example = [("M", "1M", 0.00445), ("M", "2M", 0.00949), ("M", "3M", 0.01234),\
                ("M", "6M", 0.01776), ("M", "9M", 0.01935), ("M", "1Y", 0.02084), ("S", "2Y", 0.01652),\
                ("S", "3Y", 0.02018), ("S", "4Y", 0.02303), ("S", "5Y", 0.02525), ("S", "6Y", 0.02696),\
                ("S", "7Y", 0.02825), ("S", "8Y", 0.02931),("S", "9Y", 0.03017),("S", "10Y", 0.03092),\
                ("S", "11Y", 0.03160),("S", "12Y", 0.03231),("S", "15Y", 0.03367), ("S", "20Y", 0.03419),\
                ("S", "25Y", 0.03411),("S", "30Y", 0.03412)]

            instrument_types =  [tp for (tp, tenor, rate) in open_gamma_market_data_example]
            tenors =  [tenor for (tp, tenor, rate) in open_gamma_market_data_example]
            rates =  [rate for (tp, tenor, rate) in open_gamma_market_data_example]

            value_date = datetime.strptime("13/06/2011", "%d/%m/%Y")
    
            self.crv = IRZeroCurve(value_date, instrument_types, tenors, rates, "ACT/360", "6M", "3M", "30/360",  "ACT/360", "M", "None")
            self.crv.build()
            #print(self.crv)
            
        def testTenors(self):
            self.assertEqual(self.crv.result_curve[1].tenor, datetime(2011, 7, 13))
            self.assertEqual(self.crv.result_curve[2].tenor, datetime(2011, 8, 15))
            self.assertEqual(self.crv.result_curve[3].tenor, datetime(2011, 9, 13))
            self.assertEqual(self.crv.result_curve[4].tenor, datetime(2011, 12, 13))
            self.assertEqual(self.crv.result_curve[5].tenor, datetime(2012, 3, 13))
            self.assertEqual(self.crv.result_curve[6].tenor, datetime(2012, 6, 13))
            self.assertEqual(self.crv.result_curve[7].tenor, datetime(2012, 12, 13))
            self.assertEqual(self.crv.result_curve[8].tenor, datetime(2013, 6, 13))
            self.assertEqual(self.crv.result_curve[9].tenor, datetime(2013, 12, 13))
            self.assertEqual(self.crv.result_curve[10].tenor, datetime(2014, 6, 13))
            self.assertEqual(self.crv.result_curve[11].tenor, datetime(2014, 12, 15))
            self.assertEqual(self.crv.result_curve[12].tenor, datetime(2015, 6, 15))
            
            self.assertEqual(self.crv.result_curve[64].tenor, datetime(2041, 6, 13))
               
            
        def testZeros(self):
            self.assertAlmostEqual(self.crv.result_curve[1].zero_rate, 0.00451, 5)
            self.assertAlmostEqual(self.crv.result_curve[2].zero_rate, 0.00961, 5)
            self.assertAlmostEqual(self.crv.result_curve[3].zero_rate, 0.01249, 5)
            self.assertAlmostEqual(self.crv.result_curve[4].zero_rate, 0.01793, 5)
            self.assertAlmostEqual(self.crv.result_curve[5].zero_rate, 0.01948, 5)
            self.assertAlmostEqual(self.crv.result_curve[6].zero_rate, 0.02091, 5)
            self.assertAlmostEqual(self.crv.result_curve[7].zero_rate, 0.01790, 5)
            self.assertAlmostEqual(self.crv.result_curve[8].zero_rate, 0.01640, 5)
            self.assertAlmostEqual(self.crv.result_curve[9].zero_rate, 0.01863, 5)
            self.assertAlmostEqual(self.crv.result_curve[10].zero_rate, 0.02011, 5)
            
            self.assertAlmostEqual(self.crv.result_curve[64].zero_rate, 0.03441, 5)
    unittest.main()
     
