from datetime import datetime
import ctypes
import math
from dataclasses import dataclass

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
        self.instrument_types = instrument_types
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
                
        zero_curve = self.isda_dll.JpmcdsBuildIRZeroCurve(valuation_date, "".join(self.instrument_types), tenor_dates, self.rates, \
                                                            len(self.instrument_types), self.fixedleg_freq, self.floatleg_freq, \
                                                            self.money_marketDCC, self.fixedleg_dcc, self.floatleg_dcc, \
                                                            self.badDayConvention, self.holidays)

        self.result_curve = []
        for i in range(zero_curve[0].fNumItems):
            _dt = zero_curve[0].fArray[i].fDate
            dt = datetime.strptime("".join([chr(i) for i in list(self.isda_dll.JpmcdsFormatDate(_dt))]), "%Y%m%d")
            discount_factor = self.isda_dll.JpmcdsZeroPrice(zero_curve, _dt)          
            point = IRCurvePoint(self.value_date, dt, discount_factor)            
            self.result_curve.append(point)
                
    def __str__(self):
        return "tenor,discount factor,YearFraction,Zero rate\n" + "\n".join([str(pt) for pt in self.result_curve])

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
    open_gamma_market_data_example = [("M", "1M", 0.00445),("M", "2M", 0.00949),("M", "3M", 0.01234),\
                                      ("M", "6M", 0.01776),("M", "9M", 0.01935),("M", "1Y", 0.02084),\
                                      ("S", "2Y", 0.01652),("S", "3Y", 0.02018),("S", "4Y", 0.02303),\
                                      ("S", "5Y", 0.02525),("S", "6Y", 0.02696),("S", "7Y", 0.02825),\
                                      ("S", "8Y", 0.02931),("S", "9Y", 0.03017),("S", "10Y", 0.03092),\
                                      ("S", "11Y", 0.03160),("S", "12Y", 0.03231),("S", "15Y", 0.03367),\
                                      ("S", "20Y", 0.03419),("S", "25Y", 0.03411),("S", "30Y", 0.03412)]

    instrument_types =  [tp for (tp, tenor, rate) in open_gamma_market_data_example]
    tenors =  [tenor for (tp, tenor, rate) in open_gamma_market_data_example]
    rates =  [rate for (tp, tenor, rate) in open_gamma_market_data_example]

    value_date = datetime.strptime("13/06/2011", "%d/%m/%Y")
    
    crv = IRZeroCurve(value_date, instrument_types, tenors, rates, "ACT/360", "6M", "3M", "30/360",  "ACT/360", "N", "None")
    crv.build()
    print(crv)
