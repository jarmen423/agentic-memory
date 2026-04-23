import { NavLink, Route, Routes } from "react-router-dom";
import AnswerDetailPage from "./pages/AnswerDetailPage";
import AnswersPage from "./pages/AnswersPage";
import ArmsPage from "./pages/ArmsPage";
import PoorTasksPage from "./pages/PoorTasksPage";
import RunsPage from "./pages/RunsPage";

function Nav() {
  return (
    <nav>
      <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
        Runs
      </NavLink>
      <NavLink to="/arms" className={({ isActive }) => (isActive ? "active" : "")}>
        Arms
      </NavLink>
      <NavLink to="/answers" className={({ isActive }) => (isActive ? "active" : "")}>
        Answers
      </NavLink>
      <NavLink to="/poor-tasks" className={({ isActive }) => (isActive ? "active" : "")}>
        Poor tasks
      </NavLink>
    </nav>
  );
}

export default function App() {
  return (
    <div className="layout">
      <header>
        <h1>Healthcare experiments</h1>
        <Nav />
      </header>
      <Routes>
        <Route path="/" element={<RunsPage />} />
        <Route path="/arms" element={<ArmsPage />} />
        <Route path="/answers" element={<AnswersPage />} />
        <Route path="/answers/:runId/:taskIndex" element={<AnswerDetailPage />} />
        <Route path="/poor-tasks" element={<PoorTasksPage />} />
      </Routes>
    </div>
  );
}
