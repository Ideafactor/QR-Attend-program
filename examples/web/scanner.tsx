import {AttendanceScanner} from '@attendance/attendance-react-scanner';
import '@attendance/attendance-react-scanner/style.css';
export function Scanner() {
  return <AttendanceScanner baseUrl="/api/scanner" adminHref="/"/>;
}
