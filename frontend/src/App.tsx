import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import ActivityPage from './pages/ActivityPage';
import Dashboard from './pages/Dashboard';
import DeviceControl from './pages/DeviceControl';
import EmergencyPage from './pages/EmergencyPage';
import EvaluationPage from './pages/EvaluationPage';
import VoiceAssistant from './pages/VoiceAssistant';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="voice" element={<VoiceAssistant />} />
          <Route path="devices" element={<DeviceControl />} />
          <Route path="activity" element={<ActivityPage />} />
          <Route path="emergency" element={<EmergencyPage />} />
          <Route path="evaluation" element={<EvaluationPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
