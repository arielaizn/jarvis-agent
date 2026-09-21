import type {Metadata} from 'next';
import './globals.css';
export const metadata: Metadata = {title:'JARVIS | מרכז הפיקוד', description:'מרכז הפיקוד המקומי שלך'};
export default function Layout({children}:{children:React.ReactNode}) {return <html lang="he" dir="rtl"><body>{children}</body></html>}
