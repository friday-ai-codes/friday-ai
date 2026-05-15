import React, { useState } from 'react'
import { Card } from './Card'
import { fetchData } from './api'
export interface Props {
 id: string
 initialName: string
}
export const UserCard: React.FC<Props> = (props) => {
 const [name, setName] = useState(props.initialName)
 const handleClick = => {
 fetchData(props.id).then(setName)
 }
 return (
 <div className="card">
 <Card title={name}>
 <UserAvatar size="md" />
 <span>{props.id}</span>
 <button onClick={handleClick}>Reload</button>
 </Card>
 </div>
 )
}
