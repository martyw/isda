import datetime
import ctypes
import isda.c_interface
import math

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

value_date = datetime.datetime.strptime("13/06/2011", "%d/%m/%Y")
isda_dll = isda.c_interface.CInterface()

def IRZeroCurveBuild(value_date, instrument_types, tenors, rates, money_marketDCC, fixedleg_freq, floatleg_freq, fixedleg_dcc, floatleg_dcc, badDayConvention, holidays):
    def daycount_convention(daycount_code):    
        type = (ctypes.c_long * 1)()
        isda_dll.JpmcdsStringToDayCountConv(daycount_code, type)
        
        return ctypes.c_long(type[0])
        
    def swapleg_frequency(freq):
        tmp = isda.c_interface.TDateInterval()
        isda_dll.JpmcdsStringToDateInterval(freq, object_name, tmp)
        freq_p = (ctypes.c_double * 1)()
        isda_dll.JpmcdsDateIntervalToFreq(tmp, freq_p)
        
        return ctypes.c_long(int(freq_p[0]))
        
    valuation_date = isda_dll.JpmcdsDate(value_date.year, value_date.month,value_date.day)
    object_name = "BuildZeroCurve"
    
    # tenors
    tenor_dates = []
    for tenor in tenors:
        tmp = isda.c_interface.TDateInterval()
        isda_dll.JpmcdsStringToDateInterval(tenor, object_name, tmp)
        dt = (ctypes.c_int * 1)()
        isda_dll.JpmcdsDateFwdThenAdjust(valuation_date, tmp, badDayConvention, holidays, dt)
        tenor_dates.append(dt[0])
    tenor_dates = (ctypes.c_int * len(tenor_dates))(*tenor_dates)
    
    # rates
    rates = (ctypes.c_double * len(rates))(*rates)
    
    # attributes
    mmDCC = daycount_convention(money_marketDCC)
    fixedLegFreq = swapleg_frequency(fixedleg_freq)
    floatLegFreq = swapleg_frequency(floatleg_freq)
    fixedLegDCC = daycount_convention(fixedleg_dcc)
    floatLegDCC = daycount_convention(floatleg_dcc)
    
    zero_curve = isda_dll.JpmcdsBuildIRZeroCurve(valuation_date, "".join(instrument_types), tenor_dates, rates, \
                                                len(instrument_types), fixedLegFreq, floatLegFreq, mmDCC, fixedLegDCC,\
                                                floatLegDCC, badDayConvention, holidays)

    return zero_curve[0], tenor_dates[-1]

def print_curve(zero_curve):
    for i in range(zero_curve.fNumItems):
       dt = zero_curve.fArray[i].fDate
       fmt_dt = datetime.datetime.strptime("".join([chr(i) for i in list(isda_dll.JpmcdsFormatDate(dt))]), "%Y%m%d")
       df = isda_dll.JpmcdsZeroPrice(zero_curve, dt)
       yf =  (fmt_dt - value_date).days/365.0
       zero = (-1.0*math.log(df))/yf
       
       print(f"Date:{fmt_dt}, Discount Factor:{df}, Yearfrac {yf}, Zero rate {zero}")
    
if __name__ == "__main__":
    (zero_curve, _) = IRZeroCurveBuild(value_date, instrument_types, tenors, rates, "ACT/360", "6M", "3M", "30/360",  "ACT/360", ord("N"), "None")
    print_curve(zero_curve)
