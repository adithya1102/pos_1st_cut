import { redirect } from 'next/navigation';

export default function Home() {
  const outletId = process.env.NEXT_PUBLIC_OUTLET_ID || '0b8a8349-6144-41a8-b028-b9089bd8eaea';
  redirect(`/menu?outlet_id=${outletId}&table_id=1`);
}
