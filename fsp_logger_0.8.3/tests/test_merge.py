# %% TESTS: SYNTHETIC SOFTWARE FIXTURES, NOT MEASUREMENT RESULTS
import ast
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vszh5_writer as writer
import fsp_reports as reports
import fsp_background as background

class MemoryDocumentWriter:
    """Recorder tests document construction only, not real HDF5 or Veusz."""
    latest = None
    def __init__(self,*args,**kwargs):
        self.datasets={};self.script="";type(self).latest=self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def dataset_1d(self,name,data,**kwargs):self.datasets[name]=np.array(data,copy=True)
    dataset_2d=dataset_1d
    dataset_date=dataset_1d
    def dataset_text(self,name,data,**kwargs):self.datasets[name]=list(data)
    def finish(self,script):self.script=script

def fixture():
    frequencies=np.array([1e9,1.25e9,1.5e9])
    matrices={n:np.array([[-100.,-90.,-80.],[-80.,-70.,-60.]])+n for n in (1,2,3)}
    metadata=dict(source_csv="fixture.csv",captures=2,traces=[1,2,3],
        first_timestamp="2026-10-23T12:00:00",last_timestamp="2026-10-23T12:00:02",
        timestamps=["2026-10-23T12:00:00","2026-10-23T12:00:02"])
    return frequencies,matrices,metadata

class PowerTests(unittest.TestCase):
    def test_linear_not_log_mean(self):
        self.assertAlmostEqual(float(writer.linear_power_mean_dbm([-100.,-80.])), -82.96708621881339)
    def test_extreme_levels(self):
        np.testing.assert_allclose(writer.linear_power_mean_dbm([[4000.,-4000.],[3990.,-4010.]]),np.array([4000.,-4000.])+10*np.log10(.55))
    def test_chunks_and_axis(self):
        x=np.arange(210,dtype=float).reshape(30,7)-130
        for axis in (0,1,-1):
            np.testing.assert_allclose(writer.linear_power_mean_dbm(x,axis,3),10*np.log10(np.mean(10**(x/10),axis=axis)))
    def test_reject_invalid(self):
        for x in ([],[float('nan')],[float('inf')],1.):
            with self.assertRaises(ValueError):writer.linear_power_mean_dbm(x)
    def test_statistics_use_shared_helper(self):
        f,m,_=fixture()
        with patch.object(writer,'linear_power_mean_dbm',wraps=writer.linear_power_mean_dbm) as mean:
            result=reports.trace_statistics(1,m[1],f)
            self.assertEqual(mean.call_count,1)
        np.testing.assert_allclose(result['linear_mean_dbm'],writer.linear_power_mean_dbm(m[1]))
    def test_channels_stay_separate(self):
        f,m,_=fixture()
        results=[reports.trace_statistics(n,m[n],f) for n in m]
        np.testing.assert_allclose(results[2]['linear_mean_dbm']-results[0]['linear_mean_dbm'],2.)

class PlotTests(unittest.TestCase):
    def test_page_union_and_raw_series(self):
        f,m,meta=fixture();stats=[reports.trace_statistics(n,m[n],f) for n in m]
        with patch.object(writer,'VeuszWriter',MemoryDocumentWriter):
            pages=reports.write_native_document('unused',meta,f,np.array([0.,2.]),m,stats)
        expected=['measurement_report','last_capture','Combined_Freq_vs_Time']
        expected += ['trace%d_%s'%(n,k) for n in (1,2,3) for k in ('spectral_envelope','waterfall','peak_history')]
        expected += ['Freq_1_GHz','Freq_1.25_GHz','Freq_1.5_GHz']
        self.assertEqual(set(pages),set(expected));self.assertEqual(len(pages),15)
        recorded=MemoryDocumentWriter.latest
        for n in m:
            for i,freq in enumerate(f):
                name='trace%d_Freq_%s_GHz_dbm'%(n,writer.frequency_ghz_text(freq))
                np.testing.assert_array_equal(recorded.datasets[name],m[n][:,i])
        for key in ('1 GHz','1.25 GHz','1.5 GHz'):self.assertIn(key,recorded.script)
    def test_precise_names(self):
        self.assertEqual(writer.frequency_ghz_text(1000000000.001),'1.000000000001')
    def test_utc_dates(self):
        a,_,_=reports.veusz_capture_datetimes(['2026-10-23T12:00:00-04:00'])
        b,_,_=reports.veusz_capture_datetimes(['2026-10-23T16:00:00Z'])
        np.testing.assert_array_equal(a,b)
    def test_801_bins(self):
        doc=writer.VszDoc();f=np.linspace(1e9,2e9,801)
        names=writer.frequency_time_pages(doc,f,'t',{'Trace 1':['d%d'%i for i in range(801)]})
        self.assertEqual(len(names),802)
        self.assertEqual(names[-1],'Combined_Freq_vs_Time')

class OutputTests(unittest.TestCase):
    def test_csv_order_and_immutable_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'captures.csv'
            output=background.AsyncCaptureCsvWriter(path,np.array([1.,2.]),(1,))
            data=np.array([-100.,-80.]);output.submit(datetime(2026,1,1),{1:data});data[:]=0
            output.submit(datetime(2026,1,1,0,0,1),{1:data});output.close()
            with path.open() as stream:rows=list(csv.DictReader(stream))
            self.assertEqual([float(row['trace1_dBm']) for row in rows],[-100.,-80.,0.,0.])
    def test_queue_terminal_capture(self):
        entered=threading.Event();release=threading.Event()
        original=background.AsyncCaptureCsvWriter._write_payload
        def stalled(instance,*args):
            entered.set()
            if not release.wait(5):raise RuntimeError('test timeout')
            return original(instance,*args)
        with tempfile.TemporaryDirectory() as folder,patch.object(background.AsyncCaptureCsvWriter,'_write_payload',stalled):
            output=background.AsyncCaptureCsvWriter(Path(folder)/'x.csv',np.array([1.]),(1,),queue_capacity=1)
            try:
                output.submit(datetime(2026,1,1),{1:np.array([-100.])});self.assertTrue(entered.wait(2))
                output.submit(datetime(2026,1,1,0,0,1),{1:np.array([-90.])})
                with self.assertRaises(background.CsvBacklogError):output.submit(datetime(2026,1,1,0,0,2),{1:np.array([-80.])})
            finally:release.set();output.close()
            self.assertEqual(output.written_capture_count,3)
    def test_invalid_channels(self):
        for active in ((),(1,1)):
            with self.assertRaises(ValueError):background.AsyncCaptureCsvWriter('unused',np.array([1.]),active)
    def test_mailbox(self):
        box=background.LatestCaptureMailbox();box.publish(1,None,None);box.publish(2,None,None)
        self.assertEqual(box.take()[0],2);self.assertIsNone(box.take())

class SourceTests(unittest.TestCase):
    def test_python38_grammar(self):
        for name in ('vszh5_writer.py','fsp_reports.py','fsp_background.py','rs_fsp_logger.py'):
            ast.parse((Path(__file__).resolve().parents[1]/name).read_text(),feature_version=(3,8))
    def test_gui_interlocks_and_display_no_averaging(self):
        source=(Path(__file__).resolve().parents[1]/'rs_fsp_logger.py').read_text()
        self.assertIn('autoDownsample=False, downsample=1',source)
        self.assertIn('Reports disabled during sampling, scheduled waiting, or CSV drain.',source)
        self.assertIn('self.thread is not None or self.report_process is not None',source)
        self.assertIn('self.report_btn.clicked.connect(self.on_create_reports)',source)
        self.assertIn('ThreadPoolExecutor',Path(reports.__file__).read_text())
    @unittest.skipUnless(writer.h5py is not None,'h5py unavailable: real HDF5 creation not tested')
    def test_actual_hdf5(self):
        with tempfile.TemporaryDirectory() as folder:
            f,m,meta=fixture();stats=[reports.trace_statistics(n,m[n],f) for n in m]
            path=Path(folder)/'document.vszh5'
            pages=reports.write_native_document(path,meta,f,np.array([0.,2.]),m,stats)
            self.assertEqual(pages,writer.page_names(path))

if __name__=='__main__':unittest.main(verbosity=2)
